"""OCR service for extracting text from images and scanned documents."""

import os
import tempfile
from typing import Optional, Dict, Any
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from django.conf import settings

from ..models import Document
from .storage_service import StorageService


class OCRService:
    """Service for OCR (Optical Character Recognition) operations."""
    
    def __init__(self):
        self.storage_service = StorageService()
        self.supported_languages = ['eng', 'spa', 'fra', 'deu', 'ita', 'por']
        
        # Configure Tesseract path if needed
        tesseract_cmd = getattr(settings, 'TESSERACT_CMD', None)
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    
    def extract_text(self, document: Document, language: str = 'eng') -> Optional[str]:
        """Extract text from document using OCR."""
        if not getattr(settings, 'DOCUMENTS_OCR_ENABLED', True):
            return None
        
        # Check if already processed
        if document.ocr_processed and document.ocr_text:
            return document.ocr_text
        
        # Validate language
        if language not in self.supported_languages:
            language = 'eng'
        
        extracted_text = None
        
        # Process based on file type
        if document.file_extension in ['jpg', 'jpeg', 'png', 'bmp', 'tiff']:
            extracted_text = self._ocr_image(document, language)
        elif document.file_extension == 'pdf':
            extracted_text = self._ocr_pdf(document, language)
        
        if extracted_text:
            # Update document
            document.ocr_text = extracted_text
            document.ocr_processed = True
            document.language = language[:2]  # Store language code
            document.save(update_fields=['ocr_text', 'ocr_processed', 'language'])
            
            # Update search index
            from .search_service import SearchService
            search_service = SearchService()
            search_service.index_document(document, extracted_text)
        
        return extracted_text
    
    def _ocr_image(self, document: Document, language: str) -> Optional[str]:
        """Extract text from image file."""
        try:
            # Download image
            image_content = self.storage_service.download_file(document.file_path)
            
            with tempfile.NamedTemporaryFile(suffix=f'.{document.file_extension}') as tmp_file:
                tmp_file.write(image_content)
                tmp_file.flush()
                
                # Open image
                with Image.open(tmp_file.name) as img:
                    # Convert to RGB if necessary
                    if img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')
                    
                    # Preprocess image for better OCR
                    img = self._preprocess_image(img)
                    
                    # Extract text
                    text = pytesseract.image_to_string(img, lang=language)
                    
                    # Clean extracted text
                    text = self._clean_text(text)
                    
                    return text if text.strip() else None
        
        except Exception as e:
            print(f"Error extracting text from image {document.id}: {e}")
            return None
    
    def _ocr_pdf(self, document: Document, language: str) -> Optional[str]:
        """Extract text from PDF file."""
        try:
            # Download PDF
            pdf_content = self.storage_service.download_file(document.file_path)
            
            with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp_pdf:
                tmp_pdf.write(pdf_content)
                tmp_pdf.flush()
                
                # First try to extract text directly (for text PDFs)
                direct_text = self._extract_pdf_text(tmp_pdf.name)
                if direct_text and len(direct_text.strip()) > 50:
                    return self._clean_text(direct_text)
                
                # If no text or very little text, use OCR
                all_text = []
                
                # Convert PDF pages to images
                images = convert_from_path(tmp_pdf.name, dpi=300)
                
                for i, img in enumerate(images):
                    # Preprocess image
                    img = self._preprocess_image(img)
                    
                    # Extract text from page
                    page_text = pytesseract.image_to_string(img, lang=language)
                    
                    if page_text.strip():
                        all_text.append(f"--- Page {i + 1} ---")
                        all_text.append(page_text)
                
                # Combine all text
                combined_text = '\n\n'.join(all_text)
                return self._clean_text(combined_text) if combined_text.strip() else None
        
        except Exception as e:
            print(f"Error extracting text from PDF {document.id}: {e}")
            return None
    
    def _extract_pdf_text(self, pdf_path: str) -> Optional[str]:
        """Try to extract text directly from PDF (non-OCR)."""
        try:
            import PyPDF2
            
            text_parts = []
            
            with open(pdf_path, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    
                    if text.strip():
                        text_parts.append(f"--- Page {page_num + 1} ---")
                        text_parts.append(text)
            
            return '\n\n'.join(text_parts) if text_parts else None
        
        except Exception:
            return None
    
    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """Preprocess image for better OCR results."""
        try:
            # Convert to grayscale
            if img.mode != 'L':
                img = img.convert('L')
            
            # Resize if too small
            min_size = 1000
            if img.width < min_size or img.height < min_size:
                scale = max(min_size / img.width, min_size / img.height)
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # Apply image enhancements
            from PIL import ImageEnhance, ImageFilter
            
            # Increase contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            
            # Sharpen
            img = img.filter(ImageFilter.SHARPEN)
            
            return img
        
        except Exception:
            return img
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize extracted text."""
        if not text:
            return ''
        
        # Remove multiple spaces
        import re
        text = re.sub(r'\s+', ' ', text)
        
        # Remove multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove page markers if too many
        text = re.sub(r'(--- Page \d+ ---\n){2,}', '', text)
        
        # Trim whitespace
        text = text.strip()
        
        return text
    
    def get_document_info(self, document: Document) -> Dict[str, Any]:
        """Get OCR-related information about a document."""
        info = {
            'ocr_supported': self._is_ocr_supported(document),
            'ocr_processed': document.ocr_processed,
            'has_text': bool(document.ocr_text),
            'text_length': len(document.ocr_text) if document.ocr_text else 0,
            'language': document.language,
        }
        
        if document.ocr_text:
            # Basic text statistics
            words = document.ocr_text.split()
            info['word_count'] = len(words)
            info['line_count'] = document.ocr_text.count('\n') + 1
            
            # Confidence score (if available)
            # This would require storing confidence during OCR
            info['confidence'] = None
        
        return info
    
    def _is_ocr_supported(self, document: Document) -> bool:
        """Check if document type supports OCR."""
        return document.file_extension in ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'pdf']
    
    def batch_process(self, documents: list, language: str = 'eng') -> Dict[str, Any]:
        """Process multiple documents for OCR."""
        results = {
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        for document in documents:
            if document.ocr_processed:
                results['skipped'] += 1
                continue
            
            if not self._is_ocr_supported(document):
                results['skipped'] += 1
                continue
            
            try:
                text = self.extract_text(document, language)
                if text:
                    results['processed'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'document_id': str(document.id),
                        'error': 'No text extracted'
                    })
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'document_id': str(document.id),
                    'error': str(e)
                })
        
        return results
    
    def detect_language(self, text: str) -> str:
        """Detect language of text."""
        try:
            from langdetect import detect
            lang_code = detect(text)
            
            # Map to Tesseract language codes
            lang_map = {
                'en': 'eng',
                'es': 'spa',
                'fr': 'fra',
                'de': 'deu',
                'it': 'ita',
                'pt': 'por'
            }
            
            return lang_map.get(lang_code, 'eng')
        
        except Exception:
            return 'eng'