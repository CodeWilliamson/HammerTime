import os from "os";

function getHostIP() {
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
        for (const netInterface of interfaces[name]) {
            // Skip over internal (i.e. 127.0.0.1) and non-IPv4 addresses
            if (netInterface.family === 'IPv4' && !netInterface.internal) {
                return netInterface.address;
            }
        }
    }
    return null;
}

export { getHostIP };