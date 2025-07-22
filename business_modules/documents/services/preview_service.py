"""Preview service for generating document previews."""

import os
import tempfile
import subprocess
from typing import Optional, Dict, Any
from PIL import Image
from pdf2image import convert_from_path
from django.conf import settings
import magic

from ..models import Document
from .storage_service import StorageService


class PreviewService:
    """Service for generating document previews."""
    
    def __init__(self):
        self.storage_service = StorageService()
        self.preview_sizes = {
            'thumbnail': (150, 150),
            'small': (300, 300),
            'medium': (600, 600),
            'large': (1200, 1200)
        }
    
    def generate_preview(self, document: Document, size: str = 'medium') -> Optional[str]:
        """Generate preview for a document."""
        if not getattr(settings, 'DOCUMENTS_PREVIEW_ENABLED', True):
            return None
        
        # Check if preview already exists
        if document.preview_generated and document.preview_path:
            return document.preview_path
        
        # Determine preview generation method based on file type
        preview_path = None
        
        if document.file_extension in ['jpg', 'jpeg', 'png', 'gif', 'bmp']:
            preview_path = self._generate_image_preview(document, size)
        elif document.file_extension == 'pdf':
            preview_path = self._generate_pdf_preview(document, size)
        elif document.file_extension in ['doc', 'docx']:
            preview_path = self._generate_office_preview(document, size, 'word')
        elif document.file_extension in ['xls', 'xlsx']:
            preview_path = self._generate_office_preview(document, size, 'excel')
        elif document.file_extension in ['ppt', 'pptx']:
            preview_path = self._generate_office_preview(document, size, 'powerpoint')
        elif document.file_extension in ['txt', 'md', 'csv']:
            preview_path = self._generate_text_preview(document)
        
        if preview_path:
            # Update document
            document.preview_generated = True
            document.preview_path = preview_path
            document.save(update_fields=['preview_generated', 'preview_path'])
        
        return preview_path
    
    def _generate_image_preview(self, document: Document, size: str) -> Optional[str]:
        """Generate preview for image files."""
        try:
            # Download original image
            image_content = self.storage_service.download_file(document.file_path)
            
            with tempfile.NamedTemporaryFile(suffix=f'.{document.file_extension}') as tmp_file:
                tmp_file.write(image_content)
                tmp_file.flush()
                
                # Open and resize image
                with Image.open(tmp_file.name) as img:
                    # Convert to RGB if necessary
                    if img.mode not in ('RGB', 'RGBA'):
                        img = img.convert('RGB')
                    
                    # Calculate thumbnail size maintaining aspect ratio
                    target_size = self.preview_sizes.get(size, (600, 600))
                    img.thumbnail(target_size, Image.Resampling.LANCZOS)
                    
                    # Save preview
                    preview_format = 'JPEG' if document.file_extension != 'png' else 'PNG'
                    preview_extension = 'jpg' if preview_format == 'JPEG' else 'png'
                    
                    with tempfile.NamedTemporaryFile(suffix=f'.{preview_extension}', delete=False) as preview_file:
                        img.save(preview_file.name, format=preview_format, quality=85, optimize=True)
                        
                        # Upload preview
                        with open(preview_file.name, 'rb') as f:
                            preview_content = f.read()
                        
                        preview_path = self._get_preview_path(document, size, preview_extension)
                        result = self.storage_service.upload_file(
                            preview_content,
                            preview_path,
                            f'image/{preview_extension}'
                        )
                        
                        # Clean up
                        os.unlink(preview_file.name)
                        
                        return result['path']
        
        except Exception as e:
            print(f"Error generating image preview for document {document.id}: {e}")
            return None
    
    def _generate_pdf_preview(self, document: Document, size: str) -> Optional[str]:
        """Generate preview for PDF files."""
        try:
            # Download PDF
            pdf_content = self.storage_service.download_file(document.file_path)
            
            with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp_pdf:
                tmp_pdf.write(pdf_content)
                tmp_pdf.flush()
                
                # Convert first page to image
                images = convert_from_path(
                    tmp_pdf.name,
                    first_page=1,
                    last_page=1,
                    dpi=150
                )
                
                if images:
                    img = images[0]
                    
                    # Resize image
                    target_size = self.preview_sizes.get(size, (600, 600))
                    img.thumbnail(target_size, Image.Resampling.LANCZOS)
                    
                    # Save preview
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as preview_file:
                        img.save(preview_file.name, format='JPEG', quality=85)
                        
                        # Upload preview
                        with open(preview_file.name, 'rb') as f:
                            preview_content = f.read()
                        
                        preview_path = self._get_preview_path(document, size, 'jpg')
                        result = self.storage_service.upload_file(
                            preview_content,
                            preview_path,
                            'image/jpeg'
                        )
                        
                        # Clean up
                        os.unlink(preview_file.name)
                        
                        return result['path']
        
        except Exception as e:
            print(f"Error generating PDF preview for document {document.id}: {e}")
            return None
    
    def _generate_office_preview(self, document: Document, size: str, office_type: str) -> Optional[str]:
        """Generate preview for Office documents."""
        try:
            # This would require LibreOffice or similar to convert to PDF first
            # For now, return a placeholder or skip
            return self._generate_placeholder_preview(document, office_type)
        
        except Exception as e:
            print(f"Error generating Office preview for document {document.id}: {e}")
            return None
    
    def _generate_text_preview(self, document: Document) -> Optional[str]:
        """Generate preview for text files."""
        try:
            # Download text file
            text_content = self.storage_service.download_file(document.file_path)
            
            # Decode text
            try:
                text = text_content.decode('utf-8')
            except UnicodeDecodeError:
                text = text_content.decode('latin-1')
            
            # Create preview image with text
            from PIL import ImageDraw, ImageFont
            
            # Create image
            img_width = 800
            img_height = 600
            img = Image.new('RGB', (img_width, img_height), color='white')
            draw = ImageDraw.Draw(img)
            
            # Try to use a nice font, fallback to default
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except:
                font = ImageFont.load_default()
            
            # Draw text
            lines = text.split('\n')[:30]  # First 30 lines
            y = 10
            for line in lines:
                if len(line) > 100:
                    line = line[:97] + '...'
                draw.text((10, y), line, fill='black', font=font)
                y += 20
                if y > img_height - 20:
                    break
            
            # Save preview
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as preview_file:
                img.save(preview_file.name, format='JPEG', quality=85)
                
                # Upload preview
                with open(preview_file.name, 'rb') as f:
                    preview_content = f.read()
                
                preview_path = self._get_preview_path(document, 'medium', 'jpg')
                result = self.storage_service.upload_file(
                    preview_content,
                    preview_path,
                    'image/jpeg'
                )
                
                # Clean up
                os.unlink(preview_file.name)
                
                return result['path']
        
        except Exception as e:
            print(f"Error generating text preview for document {document.id}: {e}")
            return None
    
    def _generate_placeholder_preview(self, document: Document, doc_type: str) -> Optional[str]:
        """Generate a placeholder preview for unsupported types."""
        try:
            # Create placeholder image
            img = Image.new('RGB', (400, 400), color='#f0f0f0')
            draw = ImageDraw.Draw(img)
            
            # Draw icon or text based on type
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            except:
                font = ImageFont.load_default()
                small_font = font
            
            # Draw file type
            text = document.file_extension.upper()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            x = (400 - text_width) // 2
            y = (400 - text_height) // 2 - 30
            
            draw.text((x, y), text, fill='#666666', font=font)
            
            # Draw document name
            name = document.name
            if len(name) > 30:
                name = name[:27] + '...'
            
            bbox = draw.textbbox((0, 0), name, font=small_font)
            name_width = bbox[2] - bbox[0]
            
            x = (400 - name_width) // 2
            y = 250
            
            draw.text((x, y), name, fill='#333333', font=small_font)
            
            # Save preview
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as preview_file:
                img.save(preview_file.name, format='JPEG', quality=85)
                
                # Upload preview
                with open(preview_file.name, 'rb') as f:
                    preview_content = f.read()
                
                preview_path = self._get_preview_path(document, 'medium', 'jpg')
                result = self.storage_service.upload_file(
                    preview_content,
                    preview_path,
                    'image/jpeg'
                )
                
                # Clean up
                os.unlink(preview_file.name)
                
                return result['path']
        
        except Exception as e:
            print(f"Error generating placeholder preview for document {document.id}: {e}")
            return None
    
    def _get_preview_path(self, document: Document, size: str, extension: str) -> str:
        """Generate path for preview file."""
        base_path = os.path.dirname(document.file_path)
        preview_dir = os.path.join(base_path, 'previews')
        
        filename = f"{document.id}_{size}.{extension}"
        return os.path.join(preview_dir, filename)
    
    def delete_previews(self, document: Document) -> None:
        """Delete all previews for a document."""
        if not document.preview_path:
            return
        
        # Delete main preview
        try:
            self.storage_service.delete_file(document.preview_path)
        except:
            pass
        
        # Try to delete other sizes
        base_path = os.path.dirname(document.preview_path)
        for size in self.preview_sizes:
            for ext in ['jpg', 'png']:
                preview_path = os.path.join(base_path, f"{document.id}_{size}.{ext}")
                try:
                    self.storage_service.delete_file(preview_path)
                except:
                    pass
    
    def get_mime_type(self, file_path: str) -> str:
        """Get MIME type of a file."""
        mime = magic.Magic(mime=True)
        return mime.from_file(file_path)