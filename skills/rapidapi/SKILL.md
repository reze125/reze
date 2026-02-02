---
name: rapidapi
description: RapidAPI 서버 2개 (server:8001, nocode:8002)
triggers:
  - rapidapi
  - rapid api
---
# RapidAPI Services

- Server: PM2 rapidapi-server, port 8001, /home/reze/rapidapi_server
- NoCode: PM2 rapidapi-nocode, port 8002, /home/reze/rapidapi_nocode_server
- Health: GET http://localhost:8001/health, GET http://localhost:8002/health
- Restart: pm2 restart rapidapi-server && pm2 restart rapidapi-nocode
