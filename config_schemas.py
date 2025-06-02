"""Configuration schemas for use with the SCConfigManager class."""

class ConfigSchema:
    """Base class for configuration schemas."""

    def __init__(self):
        self.default = {
            "DeviceType": {
                "Type": "PoolPump",
                "Label": "Pool Pump",
                "WebsiteBaseURL": None,
                "WebsiteAccessKey": "<Your website API key here>",
            },
            "AmberAPI": {
                "APIKey": "<Your API Key Here>",
                "BaseUrl": "https://api.amber.com.au/v1",
                "Channel": "general",
                "Timeout": 10,
            },
            "ShellySmartSwitch": {
                "Model": "Shelly1PMG3",
                "IPAddress": "<Your IP Here>",
                "SwitchID": 0,
                "DisableSwitch": False,
                "Timeout": 10,
            },
            "DeviceRunScheule": {
                "MinimumRunHoursPerDay": 3,
                "MaximumRunHoursPerDay": 9,
                "TargetRunHoursPerDay": 6,
                "MaximumPriceToRun": 20,
                "ThresholdAboveCheapestPricesForMinumumHours": 1.1,
            },
            "Files": {
                "SavedStateFile": "PowerControllerState.json",
                "RunLogFile": "PowerControllerRun.csv",
                "RunLogFileMaxLines": 480,
                "LogfileName": "PowerController.log",
                "LogfileMaxLines": 5000,
                "LogfileVerbosity": "summary",
                "ConsoleVerbosity": "summary",
                "LatestPriceData": "LatestAmberPrices.json",
            },
            "Email": {
                "EnableEmail": False,
                "SendSummary": False,
                "DailyEnergyUseThreshold": 0,
                "SendEmailsTo": "<Your email address here>",
                "SMTPServer": "<Your SMTP server here>",
                "SMTPPort": None,
                "SMTPUsername": "<Your SMTP username here>",
                "SMTPPassword": "<Your SMTP password here>",
                "SubjectPrefix": None,
            },
        }

        self.placeholders = {
            "DeviceType": {
                "WebsiteAccessKey": "<Your website API key here>",
            },
            "AmberAPI": {
                "APIKey": "<Your API Key Here>",
            },
            "ShellySmartSwitch": {
                "IPAddress": "<Your IP Here>",
            },
            "Email": {
                "SMTPUsername": "<Your SMTP username here>",
                "SMTPPassword": "<Your SMTP password here>",
            }
        }

        self.validation = {
            "DeviceType": {
                "type": "dict",
                "schema": {
                    "Type": {
                        "type": "string",
                        "required": True,
                        "allowed": ["PoolPump", "HotWaterSystem"],
                    },
                    "Label": {"type": "string", "required": True},
                    "WebsiteBaseURL": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "WebsiteAccessKey": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                },
            },
            "AmberAPI": {
                "type": "dict",
                "schema": {
                    "APIKey": {"type": "string", "required": True},
                    "BaseUrl": {"type": "string", "required": True},
                    "Channel": {
                        "type": "string",
                        "required": True,
                        "allowed": ["general", "controlledLoad"],
                    },
                    "Timeout": {
                        "type": "number",
                        "required": True,
                        "min": 5,
                        "max": 60,
                    },
                },
            },
            "ShellySmartSwitch": {
                "type": "dict",
                "schema": {
                    "Model": {
                        "type": "string",
                        "required": True,
                        "allowed": ["ShellyEM", "ShellyPlus1PM", "Shelly1PMG3"],
                    },
                    "IPAddress": {"type": "string", "required": True},
                    "SwitchID": {
                        "type": "number",
                        "required": True,
                        "min": 0,
                        "max": 3,
                    },
                    "DisableSwitch": {
                        "type": "boolean",
                        "required": False,
                        "nullable": True,
                    },
                    "Timeout": {
                        "type": "number",
                        "required": True,
                        "min": 5,
                        "max": 60,
                    },
                },
            },
            "DeviceRunScheule": {
                "type": "dict",
                "schema": {
                    "MinimumRunHoursPerDay": {
                        "type": "number",
                        "required": True,
                        "min": 1,
                        "max": 12,
                    },
                    "MaximumRunHoursPerDay": {
                        "type": "number",
                        "required": True,
                        "min": 2,
                        "max": 20,
                    },
                    "TargetRunHoursPerDay": {
                        "type": "number",
                        "required": True,
                        "min": 2,
                        "max": 20,
                    },
                    "MaximumPriceToRun": {
                        "type": "number",
                        "required": True,
                        "min": 10,
                        "max": 500,
                    },
                    "ThresholdAboveCheapestPricesForMinumumHours": {
                        "type": "number",
                        "required": True,
                        "min": 1.0,
                        "max": 2.0,
                    },
                    "MonthlyTargetRunHoursPerDay": {
                        "type": "dict",
                        "required": False,
                        "nullable": True,
                    },
                    "NoRunPeriods": {
                        "type": "list",
                        "required": False,
                        "nullable": True,
                        "schema": {
                            "type": "dict",
                            "schema": {
                                "StartDate": {
                                    "type": "string",
                                    "required": False,
                                    "regex": r"^\d{4}-\d{2}-\d{2}$",  # Validates the format YYYY-MM-DD
                                },
                                "EndDate": {
                                    "type": "string",
                                    "required": False,
                                    "regex": r"^\d{4}-\d{2}-\d{2}$",  # Validates the format YYYY-MM-DD
                                },
                            },
                        },
                    },
                },
            },
            "Files": {
                "type": "dict",
                "schema": {
                    "SavedStateFile": {"type": "string", "required": True},
                    "RunLogFile": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "RunLogFileMaxLines": {"type": "number", "min": 0, "max": 10000},
                    "LogfileName": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "LogfileMaxLines": {
                        "type": "number",
                        "min": 0,
                        "max": 100000,
                    },
                    "LogfileVerbosity": {
                        "type": "string",
                        "required": True,
                        "allowed": [
                            "none",
                            "error",
                            "warning",
                            "summary",
                            "detailed",
                            "debug",
                        ],
                    },
                    "ConsoleVerbosity": {
                        "type": "string",
                        "required": True,
                        "allowed": ["error", "warning", "summary", "detailed", "debug"],
                    },
                    "LatestPriceData": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                },
            },
            "Email": {
                "type": "dict",
                "schema": {
                    "EnableEmail": {"type": "boolean", "required": True},
                    "SendSummary": {
                        "type": "boolean",
                        "required": False,
                        "nullable": True,
                    },
                    "DailyEnergyUseThreshold": {
                        "type": "number",
                        "required": False,
                        "nullable": True,
                        "min": 0,
                        "max": 50000,
                    },
                    "SendEmailsTo": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "SMTPServer": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "SMTPPort": {
                        "type": "number",
                        "required": False,
                        "nullable": True,
                        "min": 25,
                        "max": 1000,
                    },
                    "SMTPUsername": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "SMTPPassword": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                    "SubjectPrefix": {
                        "type": "string",
                        "required": False,
                        "nullable": True,
                    },
                },
            },
        }
