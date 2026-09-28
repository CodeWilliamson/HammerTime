#!/bin/sh

IP=$(hostname -I | awk '{print $1}')

cat > /tmp/hammertime-startup.html <<EOF
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="5;url=http://localhost:3000">
<style>
html, body {
    margin: 0;
    width: 100%;
    height: 100%;
    background: #000;
    color: #fff;
    font-family: sans-serif;
}

body {
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
}

h1 {
    font-size: 6vw;
}

.ip {
    font-size: 8vw;
}
</style>
</head>
<body>
<div>
    <h1>HammerTime</h1>
    <div class="ip">$IP</div>
</div>
</body>
</html>
EOF

exec chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --noerrdialogs \
    "file:///tmp/hammertime-startup.html"