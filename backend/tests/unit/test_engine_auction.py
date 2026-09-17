"""T03-9：集合竞价撮合（02 §6.1 / §6.12 断言）。"""

from app.domain.engine import auction_match


def test_limit_buy_above_auction_price_fills_at_auction_price():
    # 买单价 ≥ 集合竞价价即成交，成交价 = 集合竞价价
    out = auction_match("buy", "limit", 10.00, 100, auction_price=9.90,
                        auction_volume=100000, participation=0.25)
    assert out.status == "filled" and out.avg_price == 9.90 and out.filled_qty == 100


def test_limit_buy_below_auction_price_waits():
    out = auction_match("buy", "limit", 9.89, 100, auction_price=9.90,
                        auction_volume=100000, participation=0.25)
    assert out.status == "wait" and out.filled_qty == 0


def test_limit_sell_below_auction_price_fills():
    out = auction_match("sell", "limit", 9.85, 100, auction_price=9.90,
                        auction_volume=100000, participation=0.25)
    assert out.status == "filled" and out.avg_price == 9.90


def test_market_fills_directly_with_simplified_volume_cap():
    # 量约束按集合竞价成交量比例简化：25000 × 0.25 …此处 vol=10000 → cap=2500
    out = auction_match("sell", "market", None, 5000, auction_price=9.90,
                        auction_volume=10000, participation=0.25)
    assert out.filled_qty == 2500 and out.status == "cancel"  # 剩余撤销
