"""
Async Notification Worker
Background worker for processing notifications from Redis Streams

Features:
- Consumes from Redis Stream "notifications"
- Processes in parallel with configurable concurrency
- Automatic retry with exponential backoff
- Dead Letter Queue (DLQ) for permanent failures
- Graceful shutdown on SIGTERM/SIGINT

Usage:
    python notification_worker.py --concurrency 5 --stream notifications

Author: ePerformance IA System
Date: 2026-09-10
"""

import asyncio
import signal
import sys
import argparse
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import json

try:
    import redis.asyncio as aioredis
except ImportError:
    print("ERROR: redis library not installed. Run: pip install redis[asyncio]")
    sys.exit(1)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.communication.notification_service import NotificationService, NotificationPriority
from backend.communication.core.models import Notification

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class NotificationWorker:
    """
    Async worker for processing notifications from Redis Streams
    
    Consumes messages from "notifications" stream and sends them via NotificationService.
    """
    
    def __init__(
        self,
        redis_url: str,
        db_url: str,
        stream_name: str = "notifications",
        consumer_group: str = "notification-workers",
        consumer_name: str = "worker-1",
        concurrency: int = 5,
        batch_size: int = 10,
        block_ms: int = 5000
    ):
        """
        Initialize worker
        
        Args:
            redis_url: Redis connection URL (redis://localhost:6379/0)
            db_url: Database connection URL
            stream_name: Redis stream to consume from
            consumer_group: Consumer group name
            consumer_name: Unique consumer identifier
            concurrency: Number of parallel tasks
            batch_size: Number of messages to fetch per batch
            block_ms: Blocking timeout for XREADGROUP
        """
        self.redis_url = redis_url
        self.db_url = db_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.concurrency = concurrency
        self.batch_size = batch_size
        self.block_ms = block_ms
        
        self.redis: Optional[aioredis.Redis] = None
        self.db_session_maker = None
        self.running = False
        self.tasks = []
        
        # Statistics
        self.stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "retried": 0,
            "started_at": None
        }
    
    async def start(self):
        """Start the worker"""
        
        logger.info(f"Starting notification worker: {self.consumer_name}")
        logger.info(f"Stream: {self.stream_name}, Group: {self.consumer_group}")
        logger.info(f"Concurrency: {self.concurrency}, Batch size: {self.batch_size}")
        
        # Connect to Redis
        self.redis = await aioredis.from_url(self.redis_url, decode_responses=True)
        
        # Setup database session
        engine = create_engine(self.db_url, pool_pre_ping=True)
        self.db_session_maker = sessionmaker(bind=engine)
        
        # Create consumer group if doesn't exist
        try:
            await self.redis.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id='0',
                mkstream=True
            )
            logger.info(f"Created consumer group: {self.consumer_group}")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.info(f"Consumer group already exists: {self.consumer_group}")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        self.running = True
        self.stats["started_at"] = datetime.utcnow()
        
        # Start consumer loop
        await self._consume_loop()
    
    async def stop(self):
        """Graceful shutdown"""
        
        logger.info("Stopping worker...")
        self.running = False
        
        # Wait for active tasks to complete (max 30s)
        if self.tasks:
            logger.info(f"Waiting for {len(self.tasks)} active tasks to complete...")
            await asyncio.wait(self.tasks, timeout=30)
        
        # Close connections
        if self.redis:
            await self.redis.close()
        
        logger.info("Worker stopped")
        self._print_stats()
    
    def _signal_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(self.stop())
    
    async def _consume_loop(self):
        """Main consume loop"""
        
        logger.info("Worker ready, waiting for messages...")
        
        while self.running:
            try:
                # Read messages from stream
                messages = await self.redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: '>'},
                    count=self.batch_size,
                    block=self.block_ms
                )
                
                if not messages:
                    continue
                
                # Process messages
                for stream_name, stream_messages in messages:
                    for message_id, message_data in stream_messages:
                        # Create task for processing
                        task = asyncio.create_task(
                            self._process_message(message_id, message_data)
                        )
                        self.tasks.append(task)
                        
                        # Limit concurrency
                        if len(self.tasks) >= self.concurrency:
                            # Wait for at least one task to complete
                            done, pending = await asyncio.wait(
                                self.tasks,
                                return_when=asyncio.FIRST_COMPLETED
                            )
                            self.tasks = list(pending)
            
            except asyncio.CancelledError:
                logger.info("Consume loop cancelled")
                break
            
            except Exception as e:
                logger.exception("Error in consume loop")
                await asyncio.sleep(5)  # Backoff before retry
    
    async def _process_message(self, message_id: str, message_data: Dict[str, str]):
        """
        Process a single notification message
        
        Args:
            message_id: Redis stream message ID
            message_data: Message payload
        """
        
        try:
            logger.info(f"Processing message {message_id}")
            
            # Parse message
            notification_id = int(message_data.get("notification_id", 0))
            user_id = int(message_data.get("user_id", 0))
            template_code = message_data.get("template_code", "")
            variables = json.loads(message_data.get("variables", "{}"))
            priority = message_data.get("priority", "medium")
            
            if not notification_id:
                logger.error(f"Invalid message (no notification_id): {message_data}")
                await self._move_to_dlq(message_id, message_data, "Invalid message")
                return
            
            # Create DB session
            db = self.db_session_maker()
            
            try:
                # Create notification service
                service = self._create_notification_service(db)
                
                # Send notification
                result = await service.send_notification(
                    user_id=user_id,
                    template_code=template_code,
                    variables=variables,
                    priority=NotificationPriority(priority)
                )
                
                if result["success"]:
                    logger.info(
                        f"Notification sent successfully",
                        extra={
                            "notification_id": notification_id,
                            "channel": result.get("channel_used")
                        }
                    )
                    self.stats["success"] += 1
                else:
                    logger.error(
                        f"Notification failed: {result.get('error')}",
                        extra={"notification_id": notification_id}
                    )
                    self.stats["failed"] += 1
                    
                    # Move to DLQ if all retries exhausted
                    notification = db.query(Notification).get(notification_id)
                    if notification and notification.attempts >= NotificationService.MAX_RETRIES:
                        await self._move_to_dlq(
                            message_id,
                            message_data,
                            result.get("error", "Max retries reached")
                        )
                
                self.stats["processed"] += 1
                
                # ACK message
                await self.redis.xack(self.stream_name, self.consumer_group, message_id)
            
            finally:
                db.close()
        
        except Exception as e:
            logger.exception(f"Error processing message {message_id}")
            self.stats["failed"] += 1
            
            # Retry later (leave message in pending for retry by another consumer)
            # Or move to DLQ after N failures
            await self._handle_processing_error(message_id, message_data, str(e))
    
    def _create_notification_service(self, db: Session) -> NotificationService:
        """Create NotificationService instance with config"""
        
        # TODO: Load from environment variables
        email_config = {
            "api_key": "xkeysib-YOUR_BREVO_KEY",
            "sender_email": "notifications@eperformance.pro",
            "sender_name": "ePerformance",
            "admin_bcc_email": "admin@eperformance.pro"
        }
        
        whatsapp_config = {
            "phone_number_id": "1079505398586828",
            "access_token": "",
            "waba_id": ""
        }
        
        telegram_config = {
            "default_bot_token": "8760593501:AAFky23ITJHGGOi96D0V-dbGEFHL_0_4vPg"
        }
        
        return NotificationService(
            db=db,
            email_config=email_config,
            whatsapp_config=whatsapp_config,
            telegram_config=telegram_config,
            redis_client=self.redis
        )
    
    async def _move_to_dlq(self, message_id: str, message_data: Dict[str, str], reason: str):
        """Move failed message to Dead Letter Queue"""
        
        dlq_stream = f"{self.stream_name}:dlq"
        
        dlq_payload = {
            **message_data,
            "original_message_id": message_id,
            "failed_at": datetime.utcnow().isoformat(),
            "failure_reason": reason
        }
        
        await self.redis.xadd(dlq_stream, dlq_payload)
        
        logger.warning(
            f"Moved message to DLQ: {message_id}",
            extra={"reason": reason}
        )
        
        # ACK original message (remove from pending)
        await self.redis.xack(self.stream_name, self.consumer_group, message_id)
    
    async def _handle_processing_error(
        self,
        message_id: str,
        message_data: Dict[str, str],
        error: str
    ):
        """
        Handle processing error
        
        Check retry count and either retry or move to DLQ
        """
        
        # Get pending entry info
        pending = await self.redis.xpending_range(
            name=self.stream_name,
            groupname=self.consumer_group,
            min=message_id,
            max=message_id,
            count=1
        )
        
        if pending:
            delivery_count = pending[0]['times_delivered']
            
            if delivery_count >= 5:  # Max 5 delivery attempts
                await self._move_to_dlq(message_id, message_data, f"Max delivery attempts: {error}")
            else:
                logger.info(f"Message will be retried (attempt {delivery_count}/5)")
                self.stats["retried"] += 1
        else:
            # ACK to avoid blocking
            await self.redis.xack(self.stream_name, self.consumer_group, message_id)
    
    def _print_stats(self):
        """Print worker statistics"""
        
        if not self.stats["started_at"]:
            return
        
        uptime = datetime.utcnow() - self.stats["started_at"]
        
        logger.info("=" * 60)
        logger.info("WORKER STATISTICS")
        logger.info("=" * 60)
        logger.info(f"Uptime: {uptime}")
        logger.info(f"Processed: {self.stats['processed']}")
        logger.info(f"Success: {self.stats['success']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Retried: {self.stats['retried']}")
        
        if self.stats["processed"] > 0:
            success_rate = (self.stats["success"] / self.stats["processed"]) * 100
            logger.info(f"Success rate: {success_rate:.2f}%")
        
        logger.info("=" * 60)


async def main():
    """CLI entry point"""
    
    parser = argparse.ArgumentParser(description="Notification Worker")
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379/0",
        help="Redis connection URL"
    )
    parser.add_argument(
        "--db-url",
        default="mysql+pymysql://user:pass@localhost/unified_ia_dev",
        help="Database connection URL"
    )
    parser.add_argument(
        "--stream",
        default="notifications",
        help="Redis stream name"
    )
    parser.add_argument(
        "--group",
        default="notification-workers",
        help="Consumer group name"
    )
    parser.add_argument(
        "--name",
        default="worker-1",
        help="Consumer name (must be unique per worker instance)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of parallel tasks"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Messages to fetch per batch"
    )
    
    args = parser.parse_args()
    
    worker = NotificationWorker(
        redis_url=args.redis_url,
        db_url=args.db_url,
        stream_name=args.stream,
        consumer_group=args.group,
        consumer_name=args.name,
        concurrency=args.concurrency,
        batch_size=args.batch_size
    )
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
