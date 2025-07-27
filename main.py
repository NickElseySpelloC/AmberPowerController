"""
main.py.

Goal: To run a high energy device pool pump (or any smart switch controlled device) based on
electricity prices from the Amber API.
"""
import sys

from sc_utility import SCConfigManager, SCLogger, ShellyControl

from config_schemas import ConfigSchema
from power_scheduler import PowerScheduler

CONFIG_FILE = "config.yaml"


def main():
    """Get our default schema, validation schema, and placeholders."""
    schemas = ConfigSchema()

    # Initialize the SC_ConfigManager class
    try:
        config = SCConfigManager(
            config_file=CONFIG_FILE,
            default_config=schemas.default,
            validation_schema=schemas.validation,
            placeholders=schemas.placeholders
        )
    except RuntimeError as e:
        print(f"Configuration file error: {e}", file=sys.stderr)
        return

    # Initialize the SC_Logger class
    try:
        logger = SCLogger(config.get_logger_settings())
    except RuntimeError as e:
        print(f"Logger initialisation error: {e}", file=sys.stderr)
        return

    # Setup email
    logger.register_email_settings(config.get_email_settings())

    # Log startup message
    this_device_label = config.get("DeviceType", "Label")
    logger.log_message("", "summary")
    logger.log_message(f"{this_device_label} starting...", "summary")

    # Create an instance of the PowerScheduler which will include the PowerSchedulerState
    # and also download the latest Amber prices for the rest of the day
    scheduler = PowerScheduler(config, schemas, logger)

    # Create an instance of the ShellyControl class
    shelly_settings = config.get_shelly_settings()
    if shelly_settings is None:
        logger.log_fatal_error("No Shelly settings found in the configuration file.")
        return
    try:
        assert isinstance(shelly_settings, dict)
        shelly_control = ShellyControl(logger, shelly_settings)
    except RuntimeError as e:
        logger.log_fatal_error(f"Shelly control initialization error: {e}")
        return
    else:
        # Register the switch with the scheduler
        scheduler.register_shelly_control(shelly_control)

    # Start the main scheduling loop
    try:
        # Get the current state of the switch or None if it's not available
        scheduler.refresh_shelly_status()

        # Make sure the switch is in the correct state
        if not scheduler.validate_device_state():
            critical_error = f"device appears to have been running for more than {config.get('DeviceRunScheule', 'MaximumRunHoursPerDay')} hours. This should never happen. See log file for details."
            logger.send_email("PowerController device was running for too long", critical_error)

        # Close out any open device runs and update the state
        scheduler.state.consolidate_device_run_data(scheduler.shelly_meter)  # type: ignore[reportCallIssue]

        # Check for roll over to prior day if required
        scheduler.state.check_day_rollover()

        # Refesh running totals
        scheduler.state.calculate_running_totals()

        # Save the state
        scheduler.state.save_state()

        # Check if we need to run the device
        should_device_run = scheduler.should_device_run()

        # Turn the switch on or off as needed if it's not already in the correct state
        _, did_change, new_state = scheduler.change_switch(should_device_run)

        # Record the switch state change and save state to file
        scheduler.log_device_state(did_change, new_state)

        # Send a heartbeat to the monitoring service
        scheduler.send_heartbeat()

        # If the prior run fails, send email that this run worked OK
        if logger.get_fatal_error():
            logger.log_message(f"{this_device_label} run was successful after a prior failure.", "summary")
            logger.clear_fatal_error()
            logger.send_email(f"{this_device_label} recovery", "PowerController run was successful after a prior failure.")
        sys.exit(0)

    # Handle any other untrapped exception
    except Exception as e:  # noqa: BLE001
        main_fatal_error = f"PowerController terminated unexpectedly due to unexpected error: {e}"
        scheduler.send_heartbeat(is_fail=True)
        logger.log_fatal_error(main_fatal_error, report_stack=True)


if __name__ == "__main__":
    # Run the main function
    main()
