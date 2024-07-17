local_path="$(dirname "$0")/Sync Charts"
rclone copy "gdrive:CH Charts" "$local_path" -vv --fast-list
echo "PRESS ENTER"
read