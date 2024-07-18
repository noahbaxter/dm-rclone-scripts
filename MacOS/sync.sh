local_path="$(dirname "$0")/Sync Charts"
rclone sync "gdrive:CH Charts" "$local_path" -vv --drive-pacer-min-sleep=10ms --drive-pacer-burst=200 --checkers=16
echo "PRESS ENTER"
read