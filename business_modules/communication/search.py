"""Message search service."""

import logging
from datetime import datetime
from typing import List, Optional

from django.contrib.auth import get_user_model
from django.contrib.postgres.search import (
    SearchVector, SearchQuery, SearchRank, TrigramSimilarity
)
from django.db import models
from django.db.models import Q, F, Value
from django.db.models.functions import Greatest

from .models import Message, Channel

User = get_user_model()
logger = logging.getLogger(__name__)


class MessageSearchService:
    """Service for searching messages."""
    
    def search(
        self,
        query: str,
        user: User,
        channel: Optional[Channel] = None,
        sender: Optional[User] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        message_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Message]:
        """Search messages with full-text search."""
        # Base queryset - messages user has access to
        queryset = Message.objects.filter(
            channel__members__user=user,
            is_deleted=False
        ).select_related(
            "sender", "channel"
        ).distinct()
        
        # Apply filters
        if channel:
            queryset = queryset.filter(channel=channel)
        
        if sender:
            queryset = queryset.filter(sender=sender)
        
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        
        if message_type:
            queryset = queryset.filter(message_type=message_type)
        
        # Full-text search
        if query:
            # Create search query
            search_query = SearchQuery(query)
            
            # Search in content and mentions
            queryset = queryset.annotate(
                search=SearchVector("content", weight="A") +
                       SearchVector("mentions", weight="B"),
                rank=SearchRank(F("search"), search_query)
            ).filter(
                Q(search=search_query) |
                Q(content__icontains=query) |  # Fallback to ILIKE
                Q(sender__username__icontains=query) |
                Q(sender__first_name__icontains=query) |
                Q(sender__last_name__icontains=query)
            ).order_by(
                "-rank", "-created_at"
            )
        else:
            queryset = queryset.order_by("-created_at")
        
        return queryset[:limit]
    
    def search_similar(
        self,
        message: Message,
        limit: int = 10
    ) -> List[Message]:
        """Find messages similar to given message."""
        # Use trigram similarity for finding similar content
        similar = Message.objects.filter(
            channel=message.channel,
            is_deleted=False
        ).exclude(
            id=message.id
        ).annotate(
            similarity=TrigramSimilarity("content", message.content)
        ).filter(
            similarity__gt=0.3  # Threshold for similarity
        ).order_by(
            "-similarity"
        )[:limit]
        
        return list(similar)
    
    def search_by_reaction(
        self,
        emoji: str,
        user: User,
        channel: Optional[Channel] = None,
        limit: int = 50
    ) -> List[Message]:
        """Search messages by reaction emoji."""
        queryset = Message.objects.filter(
            reactions__emoji=emoji,
            channel__members__user=user,
            is_deleted=False
        ).select_related(
            "sender", "channel"
        ).distinct()
        
        if channel:
            queryset = queryset.filter(channel=channel)
        
        return queryset.order_by("-created_at")[:limit]
    
    def search_by_attachment_type(
        self,
        mime_type_prefix: str,
        user: User,
        channel: Optional[Channel] = None,
        limit: int = 50
    ) -> List[Message]:
        """Search messages by attachment type."""
        queryset = Message.objects.filter(
            attachments__mime_type__startswith=mime_type_prefix,
            channel__members__user=user,
            is_deleted=False
        ).select_related(
            "sender", "channel"
        ).prefetch_related(
            "attachments"
        ).distinct()
        
        if channel:
            queryset = queryset.filter(channel=channel)
        
        return queryset.order_by("-created_at")[:limit]
    
    def index_message(self, message: Message):
        """Update search index for a message."""
        # Update search vector
        message.search_vector = SearchVector(
            Value(message.content, output_field=models.TextField()),
            weight="A"
        )
        message.save(update_fields=["search_vector"])
    
    def remove_message(self, message: Message):
        """Remove message from search index."""
        # Clear search vector
        message.search_vector = None
        message.save(update_fields=["search_vector"])


class ChannelSearchService:
    """Service for searching channels."""
    
    def search(
        self,
        query: str,
        user: User,
        channel_type: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 20
    ) -> List[Channel]:
        """Search channels."""
        # Base queryset - channels user is member of
        queryset = Channel.objects.filter(
            members__user=user
        ).distinct()
        
        # Apply filters
        if not include_archived:
            queryset = queryset.filter(is_archived=False)
        
        if channel_type:
            queryset = queryset.filter(channel_type=channel_type)
        
        # Search
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(topic__icontains=query)
            )
        
        return queryset.order_by("-last_activity")[:limit]
    
    def suggest_channels(
        self,
        user: User,
        limit: int = 10
    ) -> List[Channel]:
        """Suggest channels for user to join."""
        # Get channels user is not member of
        user_channels = Channel.objects.filter(
            members__user=user
        ).values_list("id", flat=True)
        
        # Suggest public channels with most activity
        suggested = Channel.objects.filter(
            channel_type="PUBLIC",
            is_archived=False,
            group__in=user.groups.all()
        ).exclude(
            id__in=user_channels
        ).annotate(
            activity_score=F("message_count") * F("member_count")
        ).order_by(
            "-activity_score"
        )[:limit]
        
        return list(suggested)