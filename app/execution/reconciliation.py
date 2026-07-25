from typing import Dict, List, Optional
from datetime import datetime
from app.data.models import Position, Trade
import uuid

class ReconciliationEngine:
    """Handles order reconciliation and audit trail"""
    
    def __init__(self):
        self.pending_orders: Dict[str, Dict] = {}
        self.completed_orders: Dict[str, Dict] = {}
        self.audit_log: List[Dict] = []
    
    def create_order(self, symbol: str, side: str, quantity: float, 
                    price: float, order_type: str = "MARKET") -> str:
        """Create a new order and log it"""
        order_id = str(uuid.uuid4())
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "type": order_type,
            "status": "PENDING",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        self.pending_orders[order_id] = order
        self._log_audit("ORDER_CREATED", order)
        
        return order_id
    
    def update_order_status(self, order_id: str, status: str, 
                           fill_price: Optional[float] = None) -> bool:
        """Update order status and move to completed if filled"""
        if order_id not in self.pending_orders:
            return False
        
        order = self.pending_orders[order_id]
        order["status"] = status
        order["updated_at"] = datetime.now()
        
        if fill_price is not None:
            order["fill_price"] = fill_price
        
        if status in ["FILLED", "CANCELLED", "REJECTED"]:
            # Move to completed
            self.completed_orders[order_id] = order
            del self.pending_orders[order_id]
            
        self._log_audit("ORDER_STATUS_UPDATED", order)
        
        return True
    
    def reconcile_orders(self, exchange_orders: List[Dict]) -> Dict:
        """Reconcile local orders with exchange orders"""
        reconciliation_result = {
            "matched": [],
            "unmatched_local": [],
            "unmatched_exchange": []
        }
        
        # Create lookup of exchange orders by ID
        exchange_order_ids = {order.get("id"): order for order in exchange_orders}
        
        # Check local pending orders
        for order_id, order in self.pending_orders.items():
            if order_id in exchange_order_ids:
                # Matched
                reconciliation_result["matched"].append({
                    "local": order,
                    "exchange": exchange_order_ids[order_id]
                })
            else:
                # Unmatched local
                reconciliation_result["unmatched_local"].append(order)
        
        # Check for unmatched exchange orders
        for order_id, order in exchange_order_ids.items():
            if order_id not in self.pending_orders and order_id not in self.completed_orders:
                reconciliation_result["unmatched_exchange"].append(order)
        
        self._log_audit("RECONCILIATION_PERFORMED", reconciliation_result)
        
        return reconciliation_result
    
    def get_audit_log(self) -> List[Dict]:
        """Get the audit log"""
        return self.audit_log
    
    def _log_audit(self, event_type: str, data: Dict):
        """Log an audit event"""
        audit_entry = {
            "timestamp": datetime.now(),
            "event_type": event_type,
            "data": data
        }
        self.audit_log.append(audit_entry)
    
    def get_order_status(self, order_id: str) -> Optional[str]:
        """Get status of an order"""
        if order_id in self.pending_orders:
            return self.pending_orders[order_id]["status"]
        if order_id in self.completed_orders:
            return self.completed_orders[order_id]["status"]
        return None