#!/bin/bash
cd /c/sideprojects/cognitive
source venv/Scripts/activate
docker-compose up -d
sleep 10
echo "✅ Backend: http://localhost:8000/docs"
echo "✅ Frontend: http://localhost:8501"
start http://localhost:8501
