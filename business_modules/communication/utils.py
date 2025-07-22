"""Communication module utilities."""

import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .models import NotificationTemplate

User = get_user_model()


def create_default_templates():
    """Create default notification templates."""
    templates = [
        {
            "template_id": "message_mention",
            "name": "Message Mention",
            "description": "When someone mentions you in a message",
            "subject_template": "{{ sender_name }} mentioned you",
            "body_template": "{{ sender_name }} mentioned you in #{{ channel_name }}: {{ message_preview }}",
            "email_subject": "You were mentioned in {{ channel_name }}",
            "email_body": "Hi {{ user_name }},\n\n{{ sender_name }} mentioned you in a message:\n\n{{ message_content }}\n\nView the conversation: {{ action_url }}",
            "sms_template": "{{ sender_name }} mentioned you: {{ message_preview }}",
            "push_template": "{{ sender_name }} mentioned you in {{ channel_name }}",
            "required_variables": ["sender_name", "channel_name", "message_preview", "user_name"],
            "category": "messaging",
        },
        {
            "template_id": "channel_invite",
            "name": "Channel Invitation",
            "description": "When you're invited to a channel",
            "subject_template": "You've been added to #{{ channel_name }}",
            "body_template": "{{ inviter_name }} added you to #{{ channel_name }}",
            "email_subject": "Channel invitation: {{ channel_name }}",
            "email_body": "Hi {{ user_name }},\n\n{{ inviter_name }} has added you to the channel #{{ channel_name }}.\n\n{{ channel_description }}\n\nJoin the conversation: {{ action_url }}",
            "sms_template": "{{ inviter_name }} added you to {{ channel_name }}",
            "push_template": "Added to #{{ channel_name }}",
            "required_variables": ["inviter_name", "channel_name", "user_name"],
            "category": "channels",
        },
        {
            "template_id": "meeting_scheduled",
            "name": "Meeting Scheduled",
            "description": "When a meeting is scheduled",
            "subject_template": "Meeting: {{ meeting_title }}",
            "body_template": "{{ organizer_name }} scheduled a meeting: {{ meeting_title }}",
            "email_subject": "Meeting invitation: {{ meeting_title }}",
            "email_body": "Hi {{ user_name }},\n\n{{ organizer_name }} has invited you to a meeting.\n\nTitle: {{ meeting_title }}\nTime: {{ meeting_time }}\nDuration: {{ meeting_duration }}\n\n{{ meeting_description }}\n\nJoin meeting: {{ meeting_url }}",
            "sms_template": "Meeting {{ meeting_title }} at {{ meeting_time }}",
            "push_template": "Meeting scheduled: {{ meeting_title }}",
            "required_variables": ["organizer_name", "meeting_title", "meeting_time", "user_name"],
            "category": "meetings",
        },
        {
            "template_id": "meeting_reminder",
            "name": "Meeting Reminder",
            "description": "Reminder before meeting starts",
            "subject_template": "Meeting starting soon: {{ meeting_title }}",
            "body_template": "Your meeting {{ meeting_title }} starts in {{ minutes_until }} minutes",
            "email_subject": "Meeting reminder: {{ meeting_title }}",
            "email_body": "Hi {{ user_name }},\n\nThis is a reminder that your meeting starts in {{ minutes_until }} minutes.\n\nTitle: {{ meeting_title }}\nTime: {{ meeting_time }}\n\nJoin now: {{ meeting_url }}",
            "sms_template": "Meeting {{ meeting_title }} in {{ minutes_until }} min",
            "push_template": "Meeting starting in {{ minutes_until }} minutes",
            "required_variables": ["meeting_title", "minutes_until", "meeting_time", "user_name"],
            "category": "meetings",
        },
        {
            "template_id": "task_assigned",
            "name": "Task Assigned",
            "description": "When a task is assigned to you",
            "subject_template": "New task: {{ task_title }}",
            "body_template": "{{ assigner_name }} assigned you a task: {{ task_title }}",
            "email_subject": "Task assigned: {{ task_title }}",
            "email_body": "Hi {{ user_name }},\n\n{{ assigner_name }} has assigned you a new task.\n\nTitle: {{ task_title }}\nDue: {{ due_date }}\nPriority: {{ priority }}\n\n{{ task_description }}\n\nView task: {{ action_url }}",
            "sms_template": "New task from {{ assigner_name }}: {{ task_title }}",
            "push_template": "Task assigned: {{ task_title }}",
            "required_variables": ["assigner_name", "task_title", "user_name"],
            "category": "tasks",
        },
    ]
    
    for template_data in templates:
        NotificationTemplate.objects.get_or_create(
            template_id=template_data["template_id"],
            defaults=template_data
        )


def extract_mentions(text: str) -> List[str]:
    """Extract @mentions from text."""
    pattern = r'@([a-zA-Z0-9_.-]+)'
    mentions = re.findall(pattern, text)
    return list(set(mentions))  # Remove duplicates


def extract_channel_references(text: str) -> List[str]:
    """Extract #channel references from text."""
    pattern = r'#([a-zA-Z0-9_-]+)'
    channels = re.findall(pattern, text)
    return list(set(channels))


def extract_urls(text: str) -> List[str]:
    """Extract URLs from text."""
    pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
    urls = re.findall(pattern, text)
    return urls


def format_message_preview(content: str, max_length: int = 100) -> str:
    """Format message content for preview."""
    # Remove extra whitespace
    content = ' '.join(content.split())
    
    # Truncate if needed
    if len(content) > max_length:
        content = content[:max_length - 3] + "..."
    
    return content


def generate_channel_slug(name: str, group) -> str:
    """Generate unique channel slug."""
    from .models import Channel
    
    base_slug = slugify(name)
    slug = base_slug
    counter = 1
    
    while Channel.objects.filter(group=group, slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    return slug


def parse_rich_text(text: str) -> Dict[str, Any]:
    """Parse rich text with markdown-like formatting."""
    # This is a simple parser - could be expanded
    data = {
        "text": text,
        "mentions": extract_mentions(text),
        "channels": extract_channel_references(text),
        "urls": extract_urls(text),
        "formatting": [],
    }
    
    # Detect code blocks
    code_pattern = r'```([^`]+)```'
    code_blocks = re.findall(code_pattern, text)
    if code_blocks:
        data["formatting"].append({"type": "code", "blocks": code_blocks})
    
    # Detect bold text
    bold_pattern = r'\*\*([^*]+)\*\*'
    bold_text = re.findall(bold_pattern, text)
    if bold_text:
        data["formatting"].append({"type": "bold", "text": bold_text})
    
    # Detect italic text
    italic_pattern = r'\*([^*]+)\*'
    italic_text = re.findall(italic_pattern, text)
    if italic_text:
        data["formatting"].append({"type": "italic", "text": italic_text})
    
    return data


def validate_file_type(file_name: str) -> bool:
    """Validate if file type is allowed."""
    allowed_extensions = getattr(
        settings,
        "COMMUNICATION_ALLOWED_FILE_TYPES",
        [
            'jpg', 'jpeg', 'png', 'gif', 'pdf', 'doc', 'docx',
            'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'mp4',
            'mp3', 'wav', 'zip', 'rar'
        ]
    )
    
    extension = file_name.split('.')[-1].lower()
    return extension in allowed_extensions


def get_file_icon(mime_type: str) -> str:
    """Get icon name for file type."""
    icons = {
        "image/": "image",
        "video/": "video",
        "audio/": "audio",
        "application/pdf": "file-pdf",
        "application/msword": "file-word",
        "application/vnd.ms-excel": "file-excel",
        "application/vnd.ms-powerpoint": "file-powerpoint",
        "text/": "file-text",
        "application/zip": "file-zip",
    }
    
    for prefix, icon in icons.items():
        if mime_type.startswith(prefix):
            return icon
    
    return "file"


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}h {minutes}m"
        return f"{hours}h"


def get_user_timezone(user: User) -> str:
    """Get user's timezone preference."""
    try:
        return user.notification_preferences.timezone
    except:
        return "UTC"


def sanitize_html(html: str) -> str:
    """Sanitize HTML content for safe display."""
    # This should use a proper HTML sanitization library like bleach
    # For now, just strip all HTML tags
    import re
    clean = re.compile('<.*?>')
    return re.sub(clean, '', html)


def generate_meeting_passcode(length: int = 6) -> str:
    """Generate random meeting passcode."""
    import random
    import string
    
    # Use alphanumeric characters, excluding similar looking ones
    chars = string.ascii_uppercase + string.digits
    chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    
    return ''.join(random.choice(chars) for _ in range(length))


def calculate_read_time(text: str) -> int:
    """Calculate estimated read time in seconds."""
    # Average reading speed: 200-250 words per minute
    words = len(text.split())
    wpm = 225
    seconds = (words / wpm) * 60
    return max(1, int(seconds))


def is_business_hours(timezone_str: str = "UTC") -> bool:
    """Check if current time is within business hours."""
    import pytz
    from datetime import datetime
    
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    
    # Business hours: 9 AM - 6 PM, Monday-Friday
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    
    return 9 <= now.hour < 18