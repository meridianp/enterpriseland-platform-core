"""
Template Tags for Security Headers

Provides template tags for working with security headers, especially CSP nonces.
"""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def csp_nonce(context):
    """
    Get CSP nonce from request.
    
    Usage:
        {% load security_headers %}
        <script nonce="{% csp_nonce %}">
            console.log('This script has a CSP nonce');
        </script>
    """
    request = context.get('request')
    if request and hasattr(request, 'csp_nonce'):
        return request.csp_nonce
    return ''


@register.simple_tag(takes_context=True)
def script_tag(context, src=None, type='text/javascript', **attrs):
    """
    Generate script tag with CSP nonce.
    
    Usage:
        {% load security_headers %}
        {% script_tag src="/static/js/app.js" %}
        {% script_tag type="module" %}
            import { init } from './module.js';
            init();
        {% endscript_tag %}
    """
    request = context.get('request')
    nonce = ''
    
    if request and hasattr(request, 'csp_nonce'):
        nonce = f' nonce="{request.csp_nonce}"'
    
    # Build attributes
    attr_str = ''
    if src:
        attr_str += f' src="{src}"'
    
    attr_str += f' type="{type}"'
    
    for key, value in attrs.items():
        attr_str += f' {key}="{value}"'
    
    return mark_safe(f'<script{nonce}{attr_str}>')


@register.simple_tag
def endscript_tag():
    """Close script tag"""
    return mark_safe('</script>')


@register.simple_tag(takes_context=True)
def style_tag(context, href=None, **attrs):
    """
    Generate style tag or link with CSP nonce.
    
    Usage:
        {% load security_headers %}
        {% style_tag href="/static/css/style.css" %}
        {% style_tag %}
            body { margin: 0; }
        {% endstyle_tag %}
    """
    request = context.get('request')
    nonce = ''
    
    if request and hasattr(request, 'csp_nonce'):
        nonce = f' nonce="{request.csp_nonce}"'
    
    if href:
        # External stylesheet
        attr_str = f' rel="stylesheet" href="{href}"'
        for key, value in attrs.items():
            attr_str += f' {key}="{value}"'
        return mark_safe(f'<link{nonce}{attr_str}>')
    else:
        # Inline styles
        attr_str = ''
        for key, value in attrs.items():
            attr_str += f' {key}="{value}"'
        return mark_safe(f'<style{nonce}{attr_str}>')


@register.simple_tag
def endstyle_tag():
    """Close style tag"""
    return mark_safe('</style>')


@register.simple_tag(takes_context=True)
def inline_script(context, content):
    """
    Inline script with CSP nonce.
    
    Usage:
        {% load security_headers %}
        {% inline_script "console.log('Hello');" %}
    """
    request = context.get('request')
    nonce = ''
    
    if request and hasattr(request, 'csp_nonce'):
        nonce = f' nonce="{request.csp_nonce}"'
    
    return mark_safe(f'<script{nonce}>{content}</script>')


@register.simple_tag(takes_context=True)
def inline_style(context, content):
    """
    Inline style with CSP nonce.
    
    Usage:
        {% load security_headers %}
        {% inline_style "body { margin: 0; }" %}
    """
    request = context.get('request')
    nonce = ''
    
    if request and hasattr(request, 'csp_nonce'):
        nonce = f' nonce="{request.csp_nonce}"'
    
    return mark_safe(f'<style{nonce}>{content}</style>')


@register.filter
def add_nonce(tag, request):
    """
    Add CSP nonce to existing HTML tag.
    
    Usage:
        {% load security_headers %}
        {{ '<script>alert("Hi")</script>'|add_nonce:request|safe }}
    """
    if not request or not hasattr(request, 'csp_nonce'):
        return tag
    
    nonce = request.csp_nonce
    
    # Add nonce to script tags
    tag = tag.replace('<script', f'<script nonce="{nonce}"')
    tag = tag.replace('<style', f'<style nonce="{nonce}"')
    
    return tag