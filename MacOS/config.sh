if ! command -v rclone &> /dev/null
then
    echo "Installing rclone..."
    sudo -v ; curl https://rclone.org/install.sh | sudo bash
else
    echo "rclone is already installed."
fi

echo "Configure rclone now!"
rclone config
