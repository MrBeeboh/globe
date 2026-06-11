#!/bin/bash
# Globe launcher - starts backend API and opens frontend

cd /home/mike/globe
export PYTHONPATH=/home/mike/globe

# Kill any existing processes on our ports
pkill -f "uvicorn server:app" 2>/dev/null
pkill -f "python3 -m http.server 8090" 2>/dev/null

# Start backend API server (port 8091)
cd /home/mike/globe/backend
PYTHONPATH=/home/mike/globe python3 -m uvicorn server:app --host 0.0.0.0 --port 8091 --reload > /tmp/globe-api.log 2>&1 &
API_PID=$!

# Wait for API to be ready
sleep 3

# Start frontend static server (port 8090)
cd /home/mike/globe
python3 -m http.server 8090 > /tmp/globe-frontend.log 2>&1 &
FRONTEND_PID=$!

# Open browser
sleep 1
xdg-open http://localhost:8090

# Keep script alive and show status
echo "Globe started:"
echo "  Frontend: http://localhost:8090 (PID: $FRONTEND_PID)"
echo "  API:      http://localhost:8091 (PID: $API_PID)"
echo "  Logs:     /tmp/globe-api.log, /tmp/globe-frontend.log"

# Wait for either process to exit
wait $API_PID $FRONTEND_PID