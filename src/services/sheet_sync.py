import logging
import asyncio
from typing import Dict, Any
from sqlalchemy import select

from src.db.session import async_session
from src.db.models import SheetSyncTask, SyncStatusEnum

logger = logging.getLogger(__name__)

background_tasks = set()

async def enqueue_and_process_sync(action: str, payload: dict):
    """
    Saves the sync action to the database as pending, then immediately attempts to process it.
    If it fails, it remains FAILED for the scheduler to retry.
    """
    async with async_session() as session:
        task = SheetSyncTask(
            action=action,
            payload=payload,
            status=SyncStatusEnum.PENDING
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id
        
    # Fire off background processor
    task = asyncio.create_task(process_sync_task(str(task_id)))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

async def process_sync_task(task_id: str):
    """
    Execute a specific task. If successful, mark COMPLETED. If not, mark FAILED.
    """
    # Import here to avoid circular imports dynamically
    import src.services.sheets as sheets
    import uuid
    
    async with async_session() as session:
        try:
            parsed_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except ValueError:
            logger.error(f"Invalid UUID: {task_id}")
            return
            
        task = await session.get(SheetSyncTask, parsed_uuid)
        if not task or task.status == SyncStatusEnum.COMPLETED:
            return
            
        try:
            if task.action == "APPEND_ORDER":
                await sheets._execute_append_order(task.payload)
            elif task.action == "UPDATE_FIELD":
                await sheets._execute_update_field(
                    task.payload["order_id"],
                    task.payload["field"],
                    task.payload["new_value"]
                )
            elif task.action == "UPDATE_STATUS":
                await sheets._execute_update_status(
                    task.payload["order_id"],
                    task.payload["new_status"]
                )
            else:
                logger.error(f"Unknown sync action: {task.action}")
                return
                
            task.status = SyncStatusEnum.COMPLETED
            task.error_message = None
            
        except Exception as e:
            logger.error(f"Sync task {task_id} failed: {e}")
            task.status = SyncStatusEnum.FAILED
            task.error_message = str(e)
            task.retries += 1
            
        await session.commit()

async def retry_failed_syncs():
    """
    Called by APScheduler every few minutes to retry any tasks that are FAILED or stuck PENDING.
    """
    async with async_session() as session:
        # Get tasks that failed (retries < 5). Ignore PENDING to avoid double-execution.
        stmt = select(SheetSyncTask).where(
            SheetSyncTask.status == SyncStatusEnum.FAILED,
            SheetSyncTask.retries < 5
        ).order_by(SheetSyncTask.created_at)
        
        result = await session.execute(stmt)
        tasks = result.scalars().all()
        
    if tasks:
        logger.info(f"Retrying {len(tasks)} failed Google Sheets sync tasks...")
        for task in tasks:
            await process_sync_task(str(task.id))
