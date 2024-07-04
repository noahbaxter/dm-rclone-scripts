local_path="$(dirname "$0")/Sync Charts"
rclone sync "gdrive:CH Charts" "$local_path" -vv --fast-list --checkers 4
echo "PRESS ENTER"
read
