# create_api/consumers.py
import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer

class ProjectConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        pk = self.scope['url_route']['kwargs']['project_id']  # ← FIXED
        group = f"project_{pk}"
        if not self.scope["user"].is_authenticated:
            return await self.close()
        await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        pk = self.scope['url_route']['kwargs']['project_id']  # ← FIXED
        await self.channel_layer.group_discard(f"project_{pk}", self.channel_name)

    async def project_message(self, event):
        await self.send_json(event["payload"])

