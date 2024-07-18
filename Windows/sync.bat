.\rclone.exe sync "gdrive:CH Charts" "%~dp0/Sync Charts" -vv --drive-pacer-min-sleep=10ms --drive-pacer-burst=200 --checkers=16
echo PRESS ENTER
pause