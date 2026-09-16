from clients.debra import ask_debra
from clients.gwr import ask_gwr


CLIENTS = {
    "debra": {
        "name": "DEBRA UK",
        "chatbot": "DEBRA Virtual Assistant",
        "ask": ask_debra,
    },
    "gwr": {
        "name": "Great Western Railway",
        "chatbot": "Izzy",
        "ask": ask_gwr,
    },
}
