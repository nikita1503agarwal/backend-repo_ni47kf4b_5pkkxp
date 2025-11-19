"""
Database Schemas for Casino App

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class Player(BaseModel):
    nickname: str = Field(..., description="Player display name")
    balance: float = Field(1000.0, ge=0, description="Player chip balance")
    vip_level: int = Field(0, ge=0, le=10, description="VIP tier level")

class BetHistory(BaseModel):
    player_id: str = Field(..., description="Reference to player _id as string")
    game: Literal["roulette", "slots", "blackjack"]
    amount: float = Field(..., ge=0)
    result: str = Field(..., description="Win/Lose/Push or outcome text")
    payout: float = Field(..., description="Net payout (can be negative)")
    metadata: Optional[dict] = Field(default=None, description="Game-specific details")

class BlackjackSession(BaseModel):
    player_id: str
    deck: List[str]
    player_hand: List[str]
    dealer_hand: List[str]
    status: Literal["playing", "player_bust", "dealer_bust", "player_blackjack", "dealer_blackjack", "player_stand", "finished"] = "playing"
