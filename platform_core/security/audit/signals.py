"""
Audit Logging Signals

Custom signals for audit logging system.
"""

from django.dispatch import Signal

# Signal sent when audit log is created
audit_log_created = Signal()

# Signal sent when security event is detected  
security_event_detected = Signal()

# Signal sent when anomaly is detected
anomaly_detected = Signal()

# Signal sent when data export occurs
data_exported = Signal()