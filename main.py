import os
import random
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents

app = FastAPI(title="Casino API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Utility helpers
# -----------------------------

def to_str_id(doc: Dict[str, Any]):
    if not doc:
        return doc
    d = doc.copy()
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


def new_deck() -> List[str]:
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    suits = ["♠", "♥", "♦", "♣"]
    deck = [f"{r}{s}" for r in ranks for s in suits]
    random.shuffle(deck)
    return deck


def hand_value(hand: List[str]) -> int:
    values = {"A": 11, "K": 10, "Q": 10, "J": 10, "10": 10, "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}
    total = 0
    aces = 0
    for card in hand:
        rank = card[:-1]
        total += values[rank]
        if rank == "A":
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

# -----------------------------
# Schemas
# -----------------------------

class CreatePlayer(BaseModel):
    nickname: str = Field(...)

class PlayerOut(BaseModel):
    id: str
    nickname: str
    balance: float
    vip_level: int

class RouletteBet(BaseModel):
    player_id: str
    amount: float = Field(..., gt=0)
    bet_type: str = Field(..., description="'red' | 'black' | 'number'")
    value: Optional[int] = Field(None, ge=0, le=36, description="Number for 'number' bet")

class SlotsBet(BaseModel):
    player_id: str
    amount: float = Field(..., gt=0)

class BlackjackStart(BaseModel):
    player_id: str
    amount: float = Field(..., gt=0)

class BlackjackAction(BaseModel):
    session_id: str

# -----------------------------
# Player endpoints
# -----------------------------

@app.post("/player/create")
def create_player(payload: CreatePlayer):
    # Start everyone with 1000 chips
    player_data = {"nickname": payload.nickname, "balance": 1000.0, "vip_level": 0}
    player_id = create_document("player", player_data)
    return {"id": player_id, **player_data}

@app.get("/player/{player_id}")
def get_player(player_id: str):
    player = db["player"].find_one({"_id": {"$eq": db.client.get_database(db.name).codec_options.document_class()._id if False else None}})  # placeholder to satisfy linter
    # Proper query
    from bson import ObjectId
    try:
        player = db["player"].find_one({"_id": ObjectId(player_id)})
    except Exception:
        player = None
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return to_str_id(player)

# -----------------------------
# Roulette
# -----------------------------

@app.post("/bet/roulette")
def bet_roulette(bet: RouletteBet):
    from bson import ObjectId
    player = db["player"].find_one({"_id": ObjectId(bet.player_id)})
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    if player["balance"] < bet.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # Spin wheel: numbers 0-36, 0 is green
    result = random.randint(0, 36)
    colors = {0: "green", **{n: ("red" if n in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36} else "black") for n in range(1,37)}}
    color = colors[result]

    win = False
    payout = 0.0

    if bet.bet_type == "red" or bet.bet_type == "black":
        if color == bet.bet_type:
            win = True
            payout = bet.amount  # 1:1 net win
        else:
            payout = -bet.amount
    elif bet.bet_type == "number":
        if bet.value is None:
            raise HTTPException(status_code=400, detail="Value is required for number bet")
        if result == bet.value:
            win = True
            payout = bet.amount * 35  # 35:1
        else:
            payout = -bet.amount
    else:
        raise HTTPException(status_code=400, detail="Invalid bet type")

    new_balance = player["balance"] + payout
    db["player"].update_one({"_id": ObjectId(bet.player_id)}, {"$set": {"balance": round(new_balance, 2)}})

    create_document("bethistory", {
        "player_id": bet.player_id,
        "game": "roulette",
        "amount": bet.amount,
        "result": f"{result} ({color})",
        "payout": round(payout, 2),
        "metadata": {"bet_type": bet.bet_type, "value": bet.value}
    })

    return {
        "result": result,
        "color": color,
        "payout": round(payout, 2),
        "balance": round(new_balance, 2)
    }

# -----------------------------
# Slots
# -----------------------------

@app.post("/bet/slots")
def bet_slots(bet: SlotsBet):
    from bson import ObjectId
    player = db["player"].find_one({"_id": ObjectId(bet.player_id)})
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    if player["balance"] < bet.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    symbols = ["🍒", "🍋", "🔔", "⭐", "7️⃣", "🍀"]
    reels = [random.choice(symbols) for _ in range(3)]

    payout_mult = 0
    if len(set(reels)) == 1:
        # three of a kind
        if reels[0] == "7️⃣":
            payout_mult = 20
        else:
            payout_mult = 10
    elif len(set(reels)) == 2:
        payout_mult = 2  # two of a kind

    payout = bet.amount * payout_mult - bet.amount  # net win (subtract stake)
    new_balance = player["balance"] + payout

    db["player"].update_one({"_id": ObjectId(bet.player_id)}, {"$set": {"balance": round(new_balance, 2)}})

    create_document("bethistory", {
        "player_id": bet.player_id,
        "game": "slots",
        "amount": bet.amount,
        "result": "".join(reels),
        "payout": round(payout, 2),
        "metadata": {"reels": reels, "mult": payout_mult}
    })

    return {"reels": reels, "payout": round(payout, 2), "balance": round(new_balance, 2)}

# -----------------------------
# Blackjack
# -----------------------------

@app.post("/blackjack/start")
def blackjack_start(data: BlackjackStart):
    from bson import ObjectId
    player = db["player"].find_one({"_id": ObjectId(data.player_id)})
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    if player["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    deck = new_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    session = {
        "player_id": data.player_id,
        "bet": data.amount,
        "deck": deck,
        "player_hand": player_hand,
        "dealer_hand": dealer_hand,
        "status": "playing"
    }
    session_id = create_document("blackjacksession", session)

    # If natural blackjack
    p_val = hand_value(player_hand)
    d_val = hand_value(dealer_hand)
    if p_val == 21 or d_val == 21:
        outcome = settle_blackjack(session_id)
        return {"session_id": session_id, **outcome}

    return {"session_id": session_id, "player_hand": player_hand, "dealer_hand": [dealer_hand[0], "🂠"], "status": "playing"}


def settle_blackjack(session_id: str):
    from bson import ObjectId
    session = db["blackjacksession"].find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    player = db["player"].find_one({"_id": ObjectId(session["player_id"])})
    bet = session["bet"]

    # Reveal dealer and draw to 17+
    deck = session["deck"]
    player_hand = session["player_hand"]
    dealer_hand = session["dealer_hand"]

    while hand_value(dealer_hand) < 17:
        dealer_hand.append(deck.pop())

    p_val = hand_value(player_hand)
    d_val = hand_value(dealer_hand)

    payout = 0.0
    result = "push"

    if p_val > 21:
        payout = -bet
        result = "player_bust"
    elif d_val > 21:
        payout = bet
        result = "dealer_bust"
    elif p_val == 21 and len(player_hand) == 2 and not (d_val == 21 and len(dealer_hand) == 2):
        payout = bet * 1.5
        result = "player_blackjack"
    elif d_val == 21 and len(dealer_hand) == 2 and not (p_val == 21 and len(player_hand) == 2):
        payout = -bet
        result = "dealer_blackjack"
    elif p_val > d_val:
        payout = bet
        result = "player_win"
    elif p_val < d_val:
        payout = -bet
        result = "dealer_win"
    else:
        payout = 0.0
        result = "push"

    # Update balance and session
    new_balance = player["balance"] + payout
    db["player"].update_one({"_id": ObjectId(session["player_id"])}, {"$set": {"balance": round(new_balance, 2)}})

    db["blackjacksession"].update_one({"_id": ObjectId(session_id)}, {"$set": {"deck": deck, "dealer_hand": dealer_hand, "status": "finished"}})

    create_document("bethistory", {
        "player_id": session["player_id"],
        "game": "blackjack",
        "amount": bet,
        "result": result,
        "payout": round(payout, 2),
        "metadata": {"player_hand": player_hand, "dealer_hand": dealer_hand, "p_val": p_val, "d_val": d_val}
    })

    return {
        "player_hand": player_hand,
        "dealer_hand": dealer_hand,
        "p_val": p_val,
        "d_val": d_val,
        "result": result,
        "payout": round(payout, 2),
        "balance": round(new_balance, 2),
        "status": "finished"
    }

@app.post("/blackjack/hit")
def blackjack_hit(data: BlackjackAction):
    from bson import ObjectId
    session = db["blackjacksession"].find_one({"_id": ObjectId(data.session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("status") != "playing":
        return settle_blackjack(data.session_id)

    deck = session["deck"]
    player_hand = session["player_hand"]

    player_hand.append(deck.pop())

    db["blackjacksession"].update_one({"_id": ObjectId(data.session_id)}, {"$set": {"deck": deck, "player_hand": player_hand}})

    if hand_value(player_hand) > 21:
        # Bust - settle
        return settle_blackjack(data.session_id)

    dealer_visible = [session["dealer_hand"][0], "🂠"]
    return {"session_id": data.session_id, "player_hand": player_hand, "dealer_hand": dealer_visible, "status": "playing"}

@app.post("/blackjack/stand")
def blackjack_stand(data: BlackjackAction):
    return settle_blackjack(data.session_id)

# -----------------------------
# Basic endpoints
# -----------------------------

@app.get("/")
def read_root():
    return {"message": "Casino API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": os.getenv("DATABASE_NAME") or None,
        "collections": []
    }
    try:
        if db is not None:
            response["collections"] = db.list_collection_names()[:10]
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:60]}"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
