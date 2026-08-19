from aiogram.fsm.state import State, StatesGroup


class AdminState(StatesGroup):
    """Состояния админа при обработке заказа."""
    waiting_for_subscription_link = State()
    waiting_for_amnezia_config = State()
