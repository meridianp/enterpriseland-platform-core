"""Export service for generating reports in various formats."""

import logging
import io
import json
import csv
from typing import Dict, List, Optional, Any
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.template.loader import render_to_string
from django.conf import settings

# Import third-party libraries conditionally
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    import xlsxwriter
    HAS_XLSXWRITER = True
except ImportError:
    HAS_XLSXWRITER = False

logger = logging.getLogger(__name__)


class ExportService:
    """Main export service."""
    
    def __init__(self):
        self.exporters = {
            'pdf': PDFExporter(),
            'excel': ExcelExporter(),
            'csv': CSVExporter(),
            'json': JSONExporter(),
            'html': HTMLExporter(),
        }
    
    def export(self, data: Dict, format: str, options: Dict = None) -> Dict:
        """Export data to specified format."""
        if format not in self.exporters:
            raise ValueError(f"Unsupported export format: {format}")
        
        exporter = self.exporters[format]
        return exporter.export(data, options or {})


class BaseExporter:
    """Base class for exporters."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export data and return file information."""
        raise NotImplementedError
    
    def save_file(self, content: bytes, filename: str, content_type: str) -> Dict:
        """Save file to storage and return information."""
        # Generate file path
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = f"exports/{timestamp}/{filename}"
        
        # Save to storage
        file = ContentFile(content)
        saved_path = default_storage.save(file_path, file)
        
        # Get file URL
        file_url = default_storage.url(saved_path)
        
        return {
            'file_path': saved_path,
            'file_size': len(content),
            'download_url': file_url,
            'content_type': content_type,
        }


class PDFExporter(BaseExporter):
    """Export to PDF format."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export report data to PDF."""
        if not HAS_REPORTLAB:
            raise ImportError("ReportLab is required for PDF export")
        
        # Create PDF buffer
        buffer = io.BytesIO()
        
        # Create PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )
        
        # Container for flowables
        elements = []
        styles = getSampleStyleSheet()
        
        # Add title
        report_name = data.get('report', {}).get('name', 'Report')
        title = Paragraph(report_name, styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # Add generation info
        generated_at = data.get('report', {}).get('generated_at', datetime.now().isoformat())
        info = Paragraph(f"Generated: {generated_at}", styles['Normal'])
        elements.append(info)
        elements.append(Spacer(1, 12))
        
        # Add metrics if present
        if 'metrics' in data and options.get('include_metrics', True):
            elements.append(Paragraph("Key Metrics", styles['Heading2']))
            elements.append(Spacer(1, 6))
            
            for metric in data['metrics']:
                metric_text = f"<b>{metric['name']}:</b> {metric['formatted_value']}"
                if metric.get('trend'):
                    trend = metric['trend']
                    if trend['direction'] == 'up':
                        arrow = '↑'
                    elif trend['direction'] == 'down':
                        arrow = '↓'
                    else:
                        arrow = '→'
                    metric_text += f" {arrow} {trend['change_percentage']:.1f}%"
                
                elements.append(Paragraph(metric_text, styles['Normal']))
            
            elements.append(Spacer(1, 12))
        
        # Add data tables if present
        if 'data' in data and options.get('include_raw_data', False):
            for query_id, query_data in data['data'].items():
                if 'rows' in query_data and query_data['rows']:
                    elements.append(Paragraph(f"Data: {query_id}", styles['Heading2']))
                    elements.append(Spacer(1, 6))
                    
                    # Create table
                    table_data = []
                    
                    # Add headers
                    headers = query_data.get('columns', [])
                    if headers:
                        table_data.append(headers)
                    
                    # Add rows
                    for row in query_data['rows'][:100]:  # Limit to 100 rows
                        if isinstance(row, dict):
                            table_data.append([str(row.get(col, '')) for col in headers])
                        else:
                            table_data.append([str(cell) for cell in row])
                    
                    # Create table with style
                    t = Table(table_data)
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ]))
                    
                    elements.append(t)
                    elements.append(Spacer(1, 12))
        
        # Build PDF
        doc.build(elements)
        
        # Get PDF content
        pdf_content = buffer.getvalue()
        buffer.close()
        
        # Save file
        filename = f"{report_name.replace(' ', '_')}.pdf"
        return self.save_file(pdf_content, filename, 'application/pdf')


class ExcelExporter(BaseExporter):
    """Export to Excel format."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export report data to Excel."""
        if HAS_PANDAS:
            return self._export_with_pandas(data, options)
        elif HAS_XLSXWRITER:
            return self._export_with_xlsxwriter(data, options)
        else:
            raise ImportError("pandas or xlsxwriter is required for Excel export")
    
    def _export_with_pandas(self, data: Dict, options: Dict) -> Dict:
        """Export using pandas."""
        buffer = io.BytesIO()
        
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # Add summary sheet
            summary_data = {
                'Report': [data.get('report', {}).get('name', 'Report')],
                'Generated': [data.get('report', {}).get('generated_at', datetime.now().isoformat())],
                'Type': [data.get('report', {}).get('type', 'Standard')],
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Add metrics sheet if present
            if 'metrics' in data:
                metrics_data = []
                for metric in data['metrics']:
                    metrics_data.append({
                        'Metric': metric['name'],
                        'Value': metric['value'],
                        'Formatted': metric['formatted_value'],
                        'Status': metric.get('status', 'normal'),
                        'Trend': metric.get('trend', {}).get('direction', 'stable'),
                    })
                
                if metrics_data:
                    metrics_df = pd.DataFrame(metrics_data)
                    metrics_df.to_excel(writer, sheet_name='Metrics', index=False)
            
            # Add data sheets
            if 'data' in data:
                for query_id, query_data in data['data'].items():
                    if 'rows' in query_data and query_data['rows']:
                        # Convert to DataFrame
                        df = pd.DataFrame(query_data['rows'])
                        
                        # Truncate sheet name if too long
                        sheet_name = query_id[:31] if len(query_id) > 31 else query_id
                        
                        # Write to Excel
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                        
                        # Get worksheet
                        worksheet = writer.sheets[sheet_name]
                        
                        # Auto-adjust columns width
                        for idx, col in enumerate(df.columns):
                            series = df[col]
                            max_len = max(
                                series.astype(str).map(len).max(),
                                len(str(series.name))
                            ) + 2
                            worksheet.set_column(idx, idx, max_len)
        
        # Get Excel content
        excel_content = buffer.getvalue()
        buffer.close()
        
        # Save file
        report_name = data.get('report', {}).get('name', 'Report')
        filename = f"{report_name.replace(' ', '_')}.xlsx"
        return self.save_file(excel_content, filename, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    
    def _export_with_xlsxwriter(self, data: Dict, options: Dict) -> Dict:
        """Export using xlsxwriter directly."""
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer)
        
        # Add formats
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#D7E4BD',
            'border': 1
        })
        
        # Add summary sheet
        summary_sheet = workbook.add_worksheet('Summary')
        summary_sheet.write('A1', 'Report', header_format)
        summary_sheet.write('B1', data.get('report', {}).get('name', 'Report'))
        summary_sheet.write('A2', 'Generated', header_format)
        summary_sheet.write('B2', data.get('report', {}).get('generated_at', datetime.now().isoformat()))
        
        # Add data sheets
        if 'data' in data:
            for query_id, query_data in data['data'].items():
                if 'rows' in query_data and query_data['rows']:
                    # Truncate sheet name if too long
                    sheet_name = query_id[:31] if len(query_id) > 31 else query_id
                    worksheet = workbook.add_worksheet(sheet_name)
                    
                    # Write headers
                    headers = query_data.get('columns', [])
                    for col, header in enumerate(headers):
                        worksheet.write(0, col, header, header_format)
                    
                    # Write data
                    for row_idx, row in enumerate(query_data['rows'], 1):
                        if isinstance(row, dict):
                            for col, header in enumerate(headers):
                                worksheet.write(row_idx, col, row.get(header, ''))
                        else:
                            for col, value in enumerate(row):
                                worksheet.write(row_idx, col, value)
        
        workbook.close()
        
        # Get Excel content
        excel_content = buffer.getvalue()
        buffer.close()
        
        # Save file
        report_name = data.get('report', {}).get('name', 'Report')
        filename = f"{report_name.replace(' ', '_')}.xlsx"
        return self.save_file(excel_content, filename, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class CSVExporter(BaseExporter):
    """Export to CSV format."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export report data to CSV."""
        # For CSV, we'll export the first data query or combine all
        combine_all = options.get('combine_all', False)
        
        buffer = io.StringIO()
        
        if 'data' in data:
            if combine_all:
                # Combine all data into one CSV
                writer = None
                for query_id, query_data in data['data'].items():
                    if 'rows' in query_data and query_data['rows']:
                        if writer is None:
                            # Initialize writer with first dataset
                            headers = query_data.get('columns', [])
                            writer = csv.DictWriter(buffer, fieldnames=headers)
                            writer.writeheader()
                        
                        for row in query_data['rows']:
                            if isinstance(row, dict):
                                writer.writerow(row)
            else:
                # Export first dataset only
                for query_id, query_data in data['data'].items():
                    if 'rows' in query_data and query_data['rows']:
                        headers = query_data.get('columns', [])
                        writer = csv.DictWriter(buffer, fieldnames=headers)
                        writer.writeheader()
                        
                        for row in query_data['rows']:
                            if isinstance(row, dict):
                                writer.writerow(row)
                        break
        
        # Get CSV content
        csv_content = buffer.getvalue().encode('utf-8')
        buffer.close()
        
        # Save file
        report_name = data.get('report', {}).get('name', 'Report')
        filename = f"{report_name.replace(' ', '_')}.csv"
        return self.save_file(csv_content, filename, 'text/csv')


class JSONExporter(BaseExporter):
    """Export to JSON format."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export report data to JSON."""
        # Pretty print JSON
        json_content = json.dumps(data, indent=2, default=str).encode('utf-8')
        
        # Save file
        report_name = data.get('report', {}).get('name', 'Report')
        filename = f"{report_name.replace(' ', '_')}.json"
        return self.save_file(json_content, filename, 'application/json')


class HTMLExporter(BaseExporter):
    """Export to HTML format."""
    
    def export(self, data: Dict, options: Dict) -> Dict:
        """Export report data to HTML."""
        # Use template to generate HTML
        template_name = options.get('template', 'reporting/exports/report.html')
        
        try:
            html_content = render_to_string(template_name, {
                'data': data,
                'options': options,
                'generated_at': datetime.now(),
            })
        except Exception as e:
            # Fallback to basic HTML
            html_content = self._generate_basic_html(data, options)
        
        # Save file
        report_name = data.get('report', {}).get('name', 'Report')
        filename = f"{report_name.replace(' ', '_')}.html"
        return self.save_file(html_content.encode('utf-8'), filename, 'text/html')
    
    def _generate_basic_html(self, data: Dict, options: Dict) -> str:
        """Generate basic HTML without template."""
        report = data.get('report', {})
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{report.get('name', 'Report')}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; font-weight: bold; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .metric {{ margin: 10px 0; padding: 10px; background: #f0f0f0; border-radius: 5px; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #215788; }}
    </style>
</head>
<body>
    <h1>{report.get('name', 'Report')}</h1>
    <p>Generated: {report.get('generated_at', datetime.now().isoformat())}</p>
"""
        
        # Add metrics
        if 'metrics' in data:
            html += "<h2>Key Metrics</h2>"
            for metric in data['metrics']:
                html += f"""
    <div class="metric">
        <strong>{metric['name']}:</strong>
        <span class="metric-value">{metric['formatted_value']}</span>
"""
                if metric.get('trend'):
                    trend = metric['trend']
                    arrow = '↑' if trend['direction'] == 'up' else '↓' if trend['direction'] == 'down' else '→'
                    color = 'green' if trend['direction'] == 'up' else 'red' if trend['direction'] == 'down' else 'gray'
                    html += f' <span style="color: {color}">{arrow} {trend["change_percentage"]:.1f}%</span>'
                
                html += "</div>"
        
        # Add data tables
        if 'data' in data and options.get('include_raw_data', False):
            for query_id, query_data in data['data'].items():
                if 'rows' in query_data and query_data['rows']:
                    html += f"<h2>Data: {query_id}</h2>"
                    html += "<table>"
                    
                    # Headers
                    headers = query_data.get('columns', [])
                    if headers:
                        html += "<tr>"
                        for header in headers:
                            html += f"<th>{header}</th>"
                        html += "</tr>"
                    
                    # Rows
                    for row in query_data['rows'][:100]:
                        html += "<tr>"
                        if isinstance(row, dict):
                            for header in headers:
                                html += f"<td>{row.get(header, '')}</td>"
                        else:
                            for cell in row:
                                html += f"<td>{cell}</td>"
                        html += "</tr>"
                    
                    html += "</table>"
        
        html += """
</body>
</html>
"""
        
        return html