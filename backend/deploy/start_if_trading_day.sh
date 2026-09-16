#!/bin/bash
# start_if_trading_day.sh -- only starts the service if today isn't a
# known NSE holiday. Update nse_holidays.txt yearly (NSE publishes
# their trading holiday calendar each December for the following year).

HOLIDAY_FILE="$(dirname "$0")/nse_holidays.txt"
TODAY=$(date +%Y-%m-%d)

if grep -qx "$TODAY" "$HOLIDAY_FILE" 2>/dev/null; then
    echo "$(date): $TODAY is a known NSE holiday -- not starting screener-app." >> /var/log/screener_schedule.log
    exit 0
fi

systemctl start screener-app
