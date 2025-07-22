# Communication Hub Module

A comprehensive unified communication platform for the EnterpriseLand system, providing messaging, notifications, and collaboration features.

## Features

### Core Communication
- **Internal Messaging**: Real-time chat with channels and direct messages
- **Thread Discussions**: Organized conversations with reply threads
- **Rich Text**: Support for formatting, mentions, and attachments
- **Message Search**: Full-text search across all messages
- **Read Receipts**: Track message read status
- **Typing Indicators**: See when others are typing

### Channels
- **Channel Types**: Public, Private, Direct, Announcement, External
- **Channel Management**: Create, archive, and manage members
- **Permissions**: Role-based access (Owner, Admin, Moderator, Member, Guest)
- **Auto-join**: Optionally add new team members automatically
- **Guest Access**: Allow external users in specific channels

### Notifications
- **Multi-channel**: In-app, Email, SMS, Push notifications
- **Templates**: Customizable notification templates
- **Preferences**: User-configurable notification settings
- **Quiet Hours**: Respect user's do-not-disturb times
- **Batching**: Group notifications for efficiency
- **Scheduling**: Send notifications at optimal times

### Collaboration
- **Video/Audio Calls**: Integrated video conferencing
- **Screen Sharing**: Share your screen during calls
- **Meeting Scheduling**: Plan and manage meetings
- **Calendar Integration**: Sync with external calendars
- **Recording**: Record meetings for later review
- **File Sharing**: Share documents and media

### Advanced Features
- **Message Encryption**: End-to-end encryption for sensitive data
- **Retention Policies**: Automatic message cleanup
- **Compliance**: Archive messages for regulatory requirements
- **Analytics**: Communication insights and metrics
- **Webhooks**: Integrate with external services
- **Bot Support**: Automate tasks with bots

## Installation

1. Add to `INSTALLED_APPS` in Django settings:
```python
INSTALLED_APPS = [
    # ...
    'communication',
    # ...
]
```

2. Configure settings:
```python
# Video conferencing provider
VIDEO_PROVIDER = 'jitsi'  # Options: 'jitsi', 'agora', 'twilio'

# File upload settings
COMMUNICATION_ALLOWED_FILE_TYPES = [
    'jpg', 'jpeg', 'png', 'gif', 'pdf', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'mp4',
    'mp3', 'wav', 'zip', 'rar'
]

# Message settings
MESSAGE_RETENTION_DAYS = 365
MESSAGE_ENCRYPTION_KEY = 'your-encryption-key'  # Generate securely

# Notification providers
EMAIL_PROVIDER = 'sendgrid'
SMS_PROVIDER = 'twilio'
PUSH_PROVIDER = 'firebase'
```

3. Run migrations:
```bash
python manage.py migrate communication
```

4. Create default notification templates:
```bash
python manage.py shell
>>> from communication.utils import create_default_templates
>>> create_default_templates()
```

## API Endpoints

### Channels
- `GET /api/communication/channels/` - List channels
- `POST /api/communication/channels/` - Create channel
- `GET /api/communication/channels/{id}/` - Get channel details
- `PUT /api/communication/channels/{id}/` - Update channel
- `DELETE /api/communication/channels/{id}/` - Delete channel
- `POST /api/communication/channels/{id}/add_members/` - Add members
- `POST /api/communication/channels/{id}/leave/` - Leave channel
- `POST /api/communication/channels/create_direct/` - Create DM

### Messages
- `GET /api/communication/messages/` - List messages
- `POST /api/communication/messages/` - Send message
- `PUT /api/communication/messages/{id}/` - Edit message
- `DELETE /api/communication/messages/{id}/` - Delete message
- `POST /api/communication/messages/search/` - Search messages
- `POST /api/communication/messages/{id}/add_reaction/` - Add reaction

### Notifications
- `GET /api/communication/notifications/` - List notifications
- `GET /api/communication/notifications/unread_count/` - Get unread count
- `POST /api/communication/notifications/mark_all_read/` - Mark all as read
- `POST /api/communication/notifications/{id}/mark_read/` - Mark as read

### Meetings
- `GET /api/communication/meetings/` - List meetings
- `POST /api/communication/meetings/` - Schedule meeting
- `POST /api/communication/meetings/{id}/join/` - Join meeting
- `POST /api/communication/meetings/{id}/end/` - End meeting
- `POST /api/communication/meetings/instant/` - Start instant call

## WebSocket Support

For real-time features, connect to WebSocket endpoints:

```javascript
// Connect to messaging WebSocket
const messageWs = new WebSocket('ws://localhost:8000/ws/communication/messages/');

// Send message
messageWs.send(JSON.stringify({
    type: 'message',
    channel_id: 'channel-uuid',
    content: 'Hello, world!'
}));

// Receive messages
messageWs.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('New message:', data);
};
```

## Usage Examples

### Sending a Message

```python
from communication.services import MessageService

service = MessageService()
message = service.send_message(
    channel=channel,
    sender=user,
    content="Hello team!",
    attachments=[{
        "file": file_object,
        "filename": "document.pdf",
        "file_size": 1024000,
        "mime_type": "application/pdf"
    }]
)
```

### Creating a Channel

```python
from communication.services import ChannelService

service = ChannelService()
channel = service.create_channel(
    name="Project Discussion",
    channel_type="PRIVATE",
    creator=user,
    group=group,
    members=[user1, user2, user3],
    settings={
        "allow_threading": True,
        "allow_guests": False
    }
)
```

### Sending Notifications

```python
from communication.services import NotificationService

service = NotificationService()
notification = service.send_notification(
    recipient=user,
    notification_type="TASK_ASSIGNED",
    title="New task assigned",
    content="You have been assigned to review the proposal",
    priority="HIGH",
    channels=["in_app", "email", "push"],
    template_id="task_assigned",
    template_data={
        "task_title": "Review Q4 Proposal",
        "due_date": "2024-12-15",
        "assigner_name": "John Doe"
    }
)
```

### Scheduling a Meeting

```python
from communication.services import MeetingService
from datetime import datetime, timedelta

service = MeetingService()
meeting = service.schedule_meeting(
    title="Sprint Planning",
    organizer=user,
    participants=[user1, user2, user3],
    scheduled_start=datetime.now() + timedelta(days=1),
    scheduled_end=datetime.now() + timedelta(days=1, hours=1),
    description="Quarterly sprint planning session",
    enable_recording=True
)
```

## Video Conferencing Providers

### Jitsi (Default)
- Open source, self-hosted option
- No API keys required for public instance
- Configuration:
```python
JITSI_SERVER_URL = 'https://meet.jit.si'
JITSI_JWT_SECRET = ''  # Optional for authentication
```

### Agora
- High-quality, scalable solution
- Requires account at agora.io
- Configuration:
```python
VIDEO_PROVIDER = 'agora'
AGORA_APP_ID = 'your-app-id'
AGORA_APP_CERTIFICATE = 'your-certificate'
```

### Twilio
- Enterprise-grade video API
- Requires Twilio account
- Configuration:
```python
VIDEO_PROVIDER = 'twilio'
TWILIO_ACCOUNT_SID = 'your-account-sid'
TWILIO_API_KEY = 'your-api-key'
TWILIO_API_SECRET = 'your-api-secret'
```

## Security Considerations

1. **Message Encryption**: Enable encryption for sensitive channels
2. **Access Control**: Use channel permissions to restrict access
3. **File Scanning**: Implement virus scanning for attachments
4. **Rate Limiting**: Apply rate limits to prevent spam
5. **Audit Logging**: Track all communication activities
6. **Data Retention**: Configure appropriate retention policies

## Performance Optimization

1. **Caching**: Channel members and unread counts are cached
2. **Pagination**: Use cursor pagination for message lists
3. **Search Indexing**: PostgreSQL full-text search with GIN indexes
4. **Async Tasks**: Notifications sent via Celery
5. **WebSocket**: Real-time updates without polling

## Testing

Run the test suite:

```bash
# Run all communication tests
python manage.py test communication

# Run specific test modules
python manage.py test communication.tests.test_models
python manage.py test communication.tests.test_services
python manage.py test communication.tests.test_views

# Run with coverage
coverage run --source='communication' manage.py test communication
coverage report
```

## Troubleshooting

### Messages not appearing in real-time
- Check WebSocket connection
- Verify Redis is running
- Check channel layer configuration

### Notifications not sending
- Verify provider credentials
- Check Celery workers are running
- Review notification preferences

### Video calls not connecting
- Verify video provider settings
- Check firewall/NAT settings
- Ensure HTTPS is enabled

## Contributing

1. Follow the project's coding standards
2. Write tests for new features
3. Update documentation
4. Submit pull request with clear description

## License

This module is part of the EnterpriseLand platform and follows the same license terms.