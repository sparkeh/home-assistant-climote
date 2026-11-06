"""Constants for the Climote integration."""

DOMAIN = "climote"

CONF_CLIMOTE_ID = "climote_id"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BOOST_DURATION = "boost_duration"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_POLL_INTERVAL = "poll_interval"

DEFAULT_BOOST_DURATION = "0.5"
DEFAULT_REFRESH_INTERVAL = 24
DEFAULT_POLL_INTERVAL = 5

# Boost durations (hours) offered by the Climote web form.
VALID_BOOST_VALUES = ["0.5", "1", "2", "3", "4", "5", "6"]

MIN_REFRESH_INTERVAL = 1
MAX_REFRESH_INTERVAL = 168
MIN_POLL_INTERVAL = 1
MAX_POLL_INTERVAL = 120
