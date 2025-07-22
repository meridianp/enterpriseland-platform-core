"""Search service for document full-text search."""

import json
from typing import List, Dict, Any, Optional
from django.conf import settings
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.db.models import Q, F, Value
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError, RequestError

from ..models import Document


class SearchService:
    """Service for document search functionality."""
    
    def __init__(self):
        self.use_elasticsearch = getattr(settings, 'DOCUMENTS_ELASTICSEARCH_ENABLED', True)
        
        if self.use_elasticsearch:
            self.es_client = Elasticsearch(
                hosts=getattr(settings, 'ELASTICSEARCH_HOSTS', ['localhost:9200']),
                http_auth=getattr(settings, 'ELASTICSEARCH_AUTH', None),
                scheme=getattr(settings, 'ELASTICSEARCH_SCHEME', 'http'),
                verify_certs=getattr(settings, 'ELASTICSEARCH_VERIFY_CERTS', True)
            )
            self.index_name = getattr(settings, 'DOCUMENTS_ES_INDEX', 'documents')
            self._ensure_index_exists()
    
    def _ensure_index_exists(self):
        """Ensure Elasticsearch index exists with proper mappings."""
        if not self.es_client.indices.exists(index=self.index_name):
            mappings = {
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "standard"},
                    "description": {"type": "text", "analyzer": "standard"},
                    "content": {"type": "text", "analyzer": "standard"},
                    "tags": {"type": "keyword"},
                    "category": {"type": "keyword"},
                    "file_extension": {"type": "keyword"},
                    "mime_type": {"type": "keyword"},
                    "folder_path": {"type": "text"},
                    "created_by": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "size": {"type": "long"},
                    "language": {"type": "keyword"},
                    "ocr_text": {"type": "text", "analyzer": "standard"},
                    "metadata": {"type": "object"},
                    "group_id": {"type": "keyword"},
                }
            }
            
            settings_config = {
                "number_of_shards": 1,
                "number_of_replicas": 1,
                "analysis": {
                    "analyzer": {
                        "standard": {
                            "type": "standard",
                            "stopwords": "_english_"
                        }
                    }
                }
            }
            
            self.es_client.indices.create(
                index=self.index_name,
                body={
                    "settings": settings_config,
                    "mappings": mappings
                }
            )
    
    def index_document(self, document: Document, content: str = '') -> bool:
        """Index a document for search."""
        if self.use_elasticsearch:
            return self._index_in_elasticsearch(document, content)
        else:
            return self._index_in_postgres(document, content)
    
    def _index_in_elasticsearch(self, document: Document, content: str) -> bool:
        """Index document in Elasticsearch."""
        try:
            # Prepare document data
            doc_data = {
                'id': str(document.id),
                'name': document.name,
                'description': document.description,
                'content': content,
                'tags': document.tags,
                'category': document.category,
                'file_extension': document.file_extension,
                'mime_type': document.mime_type,
                'folder_path': document.folder.path if document.folder else '/',
                'created_by': str(document.created_by.id) if document.created_by else None,
                'created_at': document.created_at.isoformat(),
                'updated_at': document.updated_at.isoformat(),
                'size': document.size,
                'language': document.language,
                'ocr_text': document.ocr_text,
                'group_id': str(document.group.id),
            }
            
            # Add metadata if available
            if hasattr(document, 'metadata'):
                doc_data['metadata'] = {
                    'title': document.metadata.title,
                    'author': document.metadata.author,
                    'subject': document.metadata.subject,
                    'keywords': document.metadata.keywords,
                }
            
            # Index document
            self.es_client.index(
                index=self.index_name,
                id=str(document.id),
                body=doc_data
            )
            
            return True
            
        except Exception as e:
            print(f"Error indexing document {document.id} in Elasticsearch: {e}")
            return False
    
    def _index_in_postgres(self, document: Document, content: str) -> bool:
        """Index document in PostgreSQL."""
        try:
            # Update search vector
            search_text = ' '.join(filter(None, [
                document.name,
                document.description,
                content,
                document.ocr_text,
                ' '.join(document.tags),
                document.category
            ]))
            
            document.search_vector = SearchVector(Value(search_text))
            document.content_extracted = True
            document.save(update_fields=['search_vector', 'content_extracted'])
            
            return True
            
        except Exception as e:
            print(f"Error indexing document {document.id} in PostgreSQL: {e}")
            return False
    
    def search_documents(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search documents."""
        if self.use_elasticsearch:
            return self._search_elasticsearch(query, document_ids, filters, limit, offset)
        else:
            return self._search_postgres(query, document_ids, filters, limit, offset)
    
    def _search_elasticsearch(
        self,
        query: str,
        document_ids: Optional[List[str]],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Search using Elasticsearch."""
        try:
            # Build query
            must_conditions = []
            filter_conditions = []
            
            # Add document ID filter if provided
            if document_ids:
                filter_conditions.append({
                    "terms": {"id": [str(id) for id in document_ids]}
                })
            
            # Add text search
            if query:
                must_conditions.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "name^3",
                            "description^2",
                            "content",
                            "ocr_text",
                            "metadata.title^2",
                            "metadata.keywords",
                            "tags"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO"
                    }
                })
            
            # Add filters
            if filters:
                if 'category' in filters:
                    filter_conditions.append({"term": {"category": filters['category']}})
                
                if 'file_extension' in filters:
                    filter_conditions.append({"term": {"file_extension": filters['file_extension']}})
                
                if 'tags' in filters:
                    filter_conditions.append({"terms": {"tags": filters['tags']}})
                
                if 'created_after' in filters:
                    filter_conditions.append({
                        "range": {"created_at": {"gte": filters['created_after']}}
                    })
                
                if 'created_before' in filters:
                    filter_conditions.append({
                        "range": {"created_at": {"lte": filters['created_before']}}
                    })
                
                if 'size_min' in filters:
                    filter_conditions.append({
                        "range": {"size": {"gte": filters['size_min']}}
                    })
                
                if 'size_max' in filters:
                    filter_conditions.append({
                        "range": {"size": {"lte": filters['size_max']}}
                    })
            
            # Build final query
            es_query = {
                "bool": {
                    "must": must_conditions if must_conditions else [{"match_all": {}}],
                    "filter": filter_conditions
                }
            }
            
            # Execute search
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": es_query,
                    "from": offset,
                    "size": limit,
                    "sort": [
                        {"_score": {"order": "desc"}},
                        {"updated_at": {"order": "desc"}}
                    ],
                    "highlight": {
                        "fields": {
                            "content": {"fragment_size": 150, "number_of_fragments": 3},
                            "description": {"fragment_size": 150, "number_of_fragments": 1}
                        }
                    }
                }
            )
            
            # Parse results
            hits = response['hits']
            documents = []
            
            for hit in hits['hits']:
                doc_data = hit['_source']
                doc_data['score'] = hit['_score']
                doc_data['highlights'] = hit.get('highlight', {})
                documents.append(doc_data)
            
            return {
                'total': hits['total']['value'],
                'documents': documents,
                'limit': limit,
                'offset': offset
            }
            
        except Exception as e:
            print(f"Error searching in Elasticsearch: {e}")
            # Fallback to PostgreSQL
            return self._search_postgres(query, document_ids, filters, limit, offset)
    
    def _search_postgres(
        self,
        query: str,
        document_ids: Optional[List[str]],
        filters: Optional[Dict[str, Any]],
        limit: int,
        offset: int
    ) -> Dict[str, Any]:
        """Search using PostgreSQL full-text search."""
        # Base queryset
        queryset = Document.objects.filter(is_deleted=False)
        
        # Filter by document IDs if provided
        if document_ids:
            queryset = queryset.filter(id__in=document_ids)
        
        # Apply filters
        if filters:
            if 'category' in filters:
                queryset = queryset.filter(category=filters['category'])
            
            if 'file_extension' in filters:
                queryset = queryset.filter(file_extension=filters['file_extension'])
            
            if 'tags' in filters:
                queryset = queryset.filter(tags__overlap=filters['tags'])
            
            if 'created_after' in filters:
                queryset = queryset.filter(created_at__gte=filters['created_after'])
            
            if 'created_before' in filters:
                queryset = queryset.filter(created_at__lte=filters['created_before'])
            
            if 'size_min' in filters:
                queryset = queryset.filter(size__gte=filters['size_min'])
            
            if 'size_max' in filters:
                queryset = queryset.filter(size__lte=filters['size_max'])
        
        # Apply text search
        if query:
            search_query = SearchQuery(query)
            queryset = queryset.annotate(
                rank=SearchRank(F('search_vector'), search_query)
            ).filter(
                Q(search_vector=search_query) |
                Q(name__icontains=query) |
                Q(description__icontains=query)
            ).order_by('-rank', '-updated_at')
        else:
            queryset = queryset.order_by('-updated_at')
        
        # Get total count
        total = queryset.count()
        
        # Apply pagination
        documents = queryset[offset:offset + limit]
        
        # Format results
        results = []
        for doc in documents:
            results.append({
                'id': str(doc.id),
                'name': doc.name,
                'description': doc.description,
                'file_extension': doc.file_extension,
                'size': doc.size,
                'created_at': doc.created_at.isoformat(),
                'updated_at': doc.updated_at.isoformat(),
                'folder_path': doc.folder.path if doc.folder else '/',
                'tags': doc.tags,
                'category': doc.category,
                'score': getattr(doc, 'rank', 0)
            })
        
        return {
            'total': total,
            'documents': results,
            'limit': limit,
            'offset': offset
        }
    
    def delete_from_index(self, document_id: str) -> bool:
        """Delete document from search index."""
        if self.use_elasticsearch:
            try:
                self.es_client.delete(
                    index=self.index_name,
                    id=document_id
                )
                return True
            except NotFoundError:
                return True  # Already deleted
            except Exception as e:
                print(f"Error deleting document {document_id} from Elasticsearch: {e}")
                return False
        
        return True
    
    def reindex_all(self, batch_size: int = 100) -> int:
        """Reindex all documents."""
        count = 0
        
        for document in Document.objects.filter(is_deleted=False).iterator(chunk_size=batch_size):
            # Get content if available
            content = ''
            if document.content_extracted and document.search_vector:
                # Extract content from existing data
                content = document.description or ''
            
            if self.index_document(document, content):
                count += 1
        
        return count
    
    def suggest_search_terms(self, prefix: str, limit: int = 10) -> List[str]:
        """Get search term suggestions."""
        if self.use_elasticsearch:
            try:
                response = self.es_client.search(
                    index=self.index_name,
                    body={
                        "suggest": {
                            "name-suggest": {
                                "prefix": prefix,
                                "completion": {
                                    "field": "name.suggest",
                                    "size": limit
                                }
                            }
                        }
                    }
                )
                
                suggestions = []
                for option in response['suggest']['name-suggest'][0]['options']:
                    suggestions.append(option['text'])
                
                return suggestions
                
            except Exception:
                pass
        
        # Fallback to simple database query
        documents = Document.objects.filter(
            name__istartswith=prefix,
            is_deleted=False
        ).values_list('name', flat=True).distinct()[:limit]
        
        return list(documents)