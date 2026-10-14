"""Pure transition rules shared by the POS API and its regression tests."""
import math

REMOTE = {'accept': 'acceptOrder', 'reject': 'rejectOrder', 'ready': 'markOrderAsReadyForPickup', 'ready_adjusted': 'markOrderWithItemsAsReadyForPickUp'}
TARGET = {'accept': 'Picking', 'reject': 'Rejected', 'ready': 'Ready', 'ready_adjusted': 'Ready', 'handover': 'Collected'}
TERMINAL = ('Collected', 'Cancelled', 'Rejected')


def check_action(state, action, operation_state='', payment_type='card_online'):
    if action == 'acknowledge':
        if state in TERMINAL:
            raise ValueError('This order is already closed.')
        return
    if operation_state in ('Sending', 'Review'):
        raise ValueError('The previous Bolt action needs manager review. Do not retry it blindly.')
    allowed = {'accept': ('New',), 'reject': ('New',), 'pick': ('Picking',),
               'ready_adjusted': ('Picking',), 'ready': ('Picking',), 'takeover': ('Picking', 'Ready'), 'handover': ('Ready',), 'shortage': ('New', 'Picking', 'Ready')}
    if state not in allowed.get(action, ()):
        raise ValueError('This action is unavailable at the current order stage. Refresh the order.')
    if action != 'reject' and payment_type != 'card_online':
        raise ValueError('Cash orders require manager review; this workflow handles Bolt online payments only.')


def validate_picks(lines, quantities):
    if not isinstance(quantities, dict) or set(quantities) != {r['id'] for r in lines}:
        raise ValueError('Picking rows do not match this order. Refresh and try again.')
    result = {}
    for row in lines:
        value = quantities[row['id']]
        if isinstance(value, bool):
            raise ValueError('Enter a valid picked quantity.')
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError('Enter a valid picked quantity.') from None
        if not math.isfinite(value) or value < 0 or value > float(row['qty']):
            raise ValueError('Picked quantity must be between zero and the ordered quantity.')
        result[row['id']] = value
    return result


def all_picked(lines, picks):
    return bool(lines) and all(float(picks.get(r['id'], -1)) == float(r['qty']) for r in lines)


def numeric_order_id(value):
    value = str(value)
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ValueError('A valid numeric Bolt order ID is required.')
    return int(value)
