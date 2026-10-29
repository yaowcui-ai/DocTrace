"""Product-only metadata. Create explicitly through the deployment CLI."""
from sqlalchemy import (MetaData, Table, Column, String, Text, DateTime, Boolean,
    ForeignKey, UniqueConstraint, CheckConstraint, Index)

metadata = MetaData()

message_sources = Table('product_message_sources', metadata,
    Column('message_id', String(36), ForeignKey('product_messages.id'), primary_key=True),
    Column('knowledge_base', String(16), nullable=False),
    CheckConstraint("knowledge_base IN ('frozen', 'managed')", name='chk_product_message_source'))

roles = Table('product_roles', metadata,
    Column('user_id', String(36), primary_key=True),
    Column('role', String(16), nullable=False),
    CheckConstraint("role IN ('user', 'admin')", name='chk_product_role'))

conversations = Table('product_conversations', metadata,
    Column('id', String(36), primary_key=True),
    Column('owner_user_id', String(36), nullable=False),
    Column('title', String(120), nullable=False),
    Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False),
    Index('ix_product_conversation_owner_updated', 'owner_user_id', 'updated_at', 'id'))

messages = Table('product_messages', metadata,
    Column('id', String(36), primary_key=True),
    Column('conversation_id', String(36), ForeignKey('product_conversations.id'), nullable=False),
    Column('owner_user_id', String(36), nullable=False),
    Column('request_id', String(36), nullable=True, unique=True),
    Column('operation_key', String(36), nullable=False),
    Column('question', Text, nullable=False),
    Column('mode', String(8), nullable=False),
    Column('query_text', Text, nullable=False),
    Column('context_method', String(48), nullable=False),
    Column('status', String(20), nullable=False),
    Column('created_at', DateTime, nullable=False),
    UniqueConstraint('owner_user_id', 'operation_key', name='uq_product_owner_operation'),
    CheckConstraint("status IN ('processing', 'completed', 'failed')", name='chk_product_message_status'),
    CheckConstraint("mode IN ('naive', 'mix')", name='chk_product_message_mode'),
    Index('ix_product_message_conversation_created', 'conversation_id', 'created_at', 'id'))

feedback = Table('product_feedback', metadata,
    Column('request_id', String(36), primary_key=True),
    Column('user_id', String(36), primary_key=True),
    Column('helpful', Boolean, nullable=False),
    Column('comment', String(2000), nullable=False, default=''),
    Column('updated_at', DateTime, nullable=False))
