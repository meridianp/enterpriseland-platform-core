"""
CDN Template Tags

Template tags for CDN integration in Django templates.
"""

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe
from django.templatetags.static import static

from platform_core.cdn.utils import get_cdn_url, should_use_cdn
from platform_core.cdn.manager import cdn_manager

register = template.Library()


@register.simple_tag
def cdn_url(path, **kwargs):
    """
    Generate CDN URL for asset.
    
    Usage:
        {% cdn_url 'images/logo.png' %}
        {% cdn_url 'images/hero.jpg' width=800 quality=85 %}
        {% cdn_url 'css/style.css' versioned=True %}
    """
    # Check if CDN should be used
    if not should_use_cdn(path):
        return static(path)
    
    # Generate CDN URL
    return get_cdn_url(path, **kwargs)


@register.simple_tag
def cdn_image(path, alt="", css_class="", **kwargs):
    """
    Generate complete image tag with CDN URL.
    
    Usage:
        {% cdn_image 'images/logo.png' alt="Logo" css_class="logo" %}
        {% cdn_image 'images/hero.jpg' alt="Hero" width=800 quality=85 %}
    """
    url = cdn_url(path, **kwargs)
    
    # Build attributes
    attrs = []
    if css_class:
        attrs.append(f'class="{css_class}"')
    if alt:
        attrs.append(f'alt="{alt}"')
    
    # Add dimension attributes if specified
    if 'width' in kwargs:
        attrs.append(f'width="{kwargs["width"]}"')
    if 'height' in kwargs:
        attrs.append(f'height="{kwargs["height"]}"')
    
    # Add loading attribute
    loading = kwargs.get('loading', 'lazy')
    attrs.append(f'loading="{loading}"')
    
    attrs_str = ' '.join(attrs)
    return mark_safe(f'<img src="{url}" {attrs_str}>')


@register.simple_tag
def cdn_picture(path, alt="", css_class="", sizes=None, **kwargs):
    """
    Generate responsive picture element with CDN URLs.
    
    Usage:
        {% cdn_picture 'images/hero.jpg' alt="Hero" sizes="(max-width: 768px) 100vw, 50vw" %}
    """
    # Generate WebP version
    webp_url = cdn_url(path, format='webp', **kwargs)
    
    # Generate AVIF version if supported
    avif_url = cdn_url(path, format='avif', **kwargs)
    
    # Original format URL
    original_url = cdn_url(path, **kwargs)
    
    # Build picture element
    html = ['<picture>']
    
    # Add AVIF source
    if getattr(settings, 'CDN_ENABLE_AVIF', False):
        html.append(f'  <source srcset="{avif_url}" type="image/avif">')
    
    # Add WebP source
    html.append(f'  <source srcset="{webp_url}" type="image/webp">')
    
    # Add sizes attribute if provided
    sizes_attr = f' sizes="{sizes}"' if sizes else ''
    
    # Add img element
    img_attrs = []
    if css_class:
        img_attrs.append(f'class="{css_class}"')
    if alt:
        img_attrs.append(f'alt="{alt}"')
    img_attrs.append('loading="lazy"')
    
    img_attrs_str = ' '.join(img_attrs)
    html.append(f'  <img src="{original_url}" {img_attrs_str}{sizes_attr}>')
    
    html.append('</picture>')
    
    return mark_safe('\n'.join(html))


@register.simple_tag
def cdn_srcset(path, widths=None, **kwargs):
    """
    Generate srcset attribute for responsive images.
    
    Usage:
        {% cdn_srcset 'images/hero.jpg' widths="320,768,1200" %}
    """
    if not widths:
        widths = [320, 768, 1200, 1920]
    elif isinstance(widths, str):
        widths = [int(w.strip()) for w in widths.split(',')]
    
    srcset_parts = []
    
    for width in widths:
        url = cdn_url(path, width=width, **kwargs)
        srcset_parts.append(f"{url} {width}w")
    
    return ' , '.join(srcset_parts)


@register.simple_tag
def cdn_preload(path, as_type=None, **kwargs):
    """
    Generate preload link tag for CDN resource.
    
    Usage:
        {% cdn_preload 'css/critical.css' as_type='style' %}
        {% cdn_preload 'fonts/main.woff2' as_type='font' crossorigin=True %}
    """
    url = cdn_url(path, **kwargs)
    
    # Determine type if not specified
    if not as_type:
        if path.endswith('.css'):
            as_type = 'style'
        elif path.endswith('.js'):
            as_type = 'script'
        elif path.endswith(('.woff', '.woff2', '.ttf')):
            as_type = 'font'
        elif path.endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif')):
            as_type = 'image'
    
    # Build attributes
    attrs = [f'href="{url}"', 'rel="preload"']
    
    if as_type:
        attrs.append(f'as="{as_type}"')
    
    # Add crossorigin for fonts
    if as_type == 'font' or kwargs.get('crossorigin'):
        attrs.append('crossorigin')
    
    attrs_str = ' '.join(attrs)
    return mark_safe(f'<link {attrs_str}>')


@register.simple_tag
def cdn_script(path, async_load=False, defer=False, module=False, **kwargs):
    """
    Generate script tag with CDN URL.
    
    Usage:
        {% cdn_script 'js/app.js' defer=True %}
        {% cdn_script 'js/module.js' module=True %}
    """
    url = cdn_url(path, **kwargs)
    
    attrs = [f'src="{url}"']
    
    if async_load:
        attrs.append('async')
    if defer:
        attrs.append('defer')
    if module:
        attrs.append('type="module"')
    
    attrs_str = ' '.join(attrs)
    return mark_safe(f'<script {attrs_str}></script>')


@register.simple_tag
def cdn_style(path, media="all", **kwargs):
    """
    Generate link tag for CSS with CDN URL.
    
    Usage:
        {% cdn_style 'css/style.css' %}
        {% cdn_style 'css/print.css' media='print' %}
    """
    url = cdn_url(path, **kwargs)
    
    attrs = [
        f'href="{url}"',
        'rel="stylesheet"',
        f'media="{media}"'
    ]
    
    attrs_str = ' '.join(attrs)
    return mark_safe(f'<link {attrs_str}>')


@register.simple_tag(takes_context=True)
def cdn_debug(context):
    """
    Display CDN debug information in development.
    
    Usage:
        {% cdn_debug %}
    """
    if not settings.DEBUG:
        return ''
    
    # Get CDN stats
    try:
        stats = cdn_manager.get_stats()
        health = cdn_manager.health_check()
        
        html = [
            '<div class="cdn-debug" style="position: fixed; bottom: 10px; right: 10px; background: #f0f0f0; padding: 10px; border: 1px solid #ccc; font-size: 12px; z-index: 9999;">',
            '<strong>CDN Debug</strong><br>',
            f'Status: {health["status"]}<br>',
            f'Provider: {health["provider_enabled"]}<br>',
            f'Hit Rate: {stats.get("provider", {}).get("cache_hit_rate", "N/A")}%<br>',
            '</div>'
        ]
        
        return mark_safe('\n'.join(html))
    except:
        return ''


@register.filter
def cdn_enabled(value=None):
    """
    Check if CDN is enabled.
    
    Usage:
        {% if True|cdn_enabled %}
            CDN is enabled
        {% endif %}
    """
    return getattr(settings, 'CDN_ENABLED', False)


@register.filter
def cdn_provider(value=None):
    """
    Get current CDN provider name.
    
    Usage:
        Current CDN: {{ True|cdn_provider }}
    """
    try:
        if cdn_manager.provider:
            return cdn_manager.provider.__class__.__name__
    except:
        pass
    
    return 'None'