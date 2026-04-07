from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)
from typing import Any
import json
import math


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()


class Trader:
    def __init__(self):

        self.limits: dict[Symbol, int] = {
            "EMERALDS": 80,
            "TOMATOES": 80,
        }

        self.orders: dict[Symbol, list[Order]] = {}
        self.conversions: int = 0
        self.traderData: str = "SAMPLE"

        self.prev_price: int | None = None
        self.prev_vol: int | None = None

        self.emeralds_buy_orders: int = 0
        self.emeralds_sell_orders: int = 0
        self.emeralds_position: int = 0

        self.tomatoes_buy_orders: int = 0
        self.tomatoes_sell_orders: int = 0
        self.tomatoes_position: int = 0

    # define easier sell and buy order functions
    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))

        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))

        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state: TradingState, product: Symbol) -> int:
        if product == "EMERALDS":
            return state.position.get("EMERALDS", 0)
        elif product == "TOMATOES":
            return state.position.get("TOMATOES", 0)
        else:
            raise ValueError(f"Unknown product: {product}")

    def search_buys(self, state, product, acceptable_price, depth=1):
        # Buys things if there are asks below or equal acceptable price
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) == 0:
            return

        orders = list(order_depth.sell_orders.items())
        for ask, amount in orders[0 : max(len(orders), depth)]:

            pos = self.get_product_pos(state, product)
            if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                if product == "EMERALDS":
                    size = min(self.limits[product] - self.get_product_pos(state, product) - self.emeralds_buy_orders, -amount)
                    self.emeralds_buy_orders += size
                    self.send_buy_order(product, ask, size, msg=f"{product}: TRADE BUY {str(size)} x @ {ask}")
                elif product == "TOMATOES":
                    size = min(self.limits[product] - self.tomatoes_position - self.tomatoes_buy_orders, -amount)
                    self.tomatoes_buy_orders += size
                    self.send_buy_order(product, ask, size, msg=f"{product}: TRADE BUY {str(size)} x @ {ask}")

    def search_sells(self, state, product, acceptable_price, depth=1):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) == 0:
            return

        orders = list(order_depth.buy_orders.items())
        for bid, amount in orders[0 : max(len(orders), depth)]:

            pos = self.get_product_pos(state, product)
            if int(bid) > acceptable_price or (abs(bid - acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                if product == "EMERALDS":
                    size = min(self.get_product_pos(state, product) + self.limits[product] - self.emeralds_sell_orders, amount)
                    self.emeralds_sell_orders += size
                    self.send_sell_order(product, bid, -size, msg=f"{product}: TRADE SELL {str(-size)} x @ {bid}")
                elif product == "TOMATOES":
                    size = min(self.get_product_pos(state, product) + self.limits[product] - self.tomatoes_sell_orders, amount)
                    self.tomatoes_sell_orders += size
                    self.send_sell_order(product, bid, -size, msg=f"{product}: TRADE SELL {str(-size)} x @ {bid}")

    def get_bid(self, state, product, price):
        return max(state.order_depths[product].buy_orders.keys(), key=lambda x: x < price)

    def get_ask(self, state, product, price):
        return min(state.order_depths[product].sell_orders.keys(), key=lambda x: x > price)

    def trade_emeralds(self, state: TradingState):
        product = "EMERALDS"

        # Buy anything at a good price
        self.search_buys(state, product, 10000, depth=3)
        self.search_sells(state, product, 10000, depth=3)

        # Market making
        best_ask = self.get_ask(state, product, 10000)
        if best_ask is not None and best_ask - 1 > 10_000:
            sell_price = best_ask - 1
        else:
            sell_price = 10007

        best_bid = self.get_bid(state, product, 10000)
        if best_bid is not None and best_bid + 1 < 10_000:
            buy_price = best_bid + 1
        else:
            buy_price = 9993

        max_buy = self.limits[product] - self.emeralds_position - self.emeralds_buy_orders
        max_sell = self.emeralds_position + self.limits[product] - self.emeralds_sell_orders

        self.send_sell_order(product, sell_price, -max_sell, msg=f"{product}: MARKET MADE Sell {max_sell} @ {sell_price}")
        self.send_buy_order(product, buy_price, max_buy, msg=f"{product}: MARKET MADE Buy {max_buy} @ {buy_price}")

    def trade_tomatoes(self, state: TradingState) -> None:
        product = "TOMATOES"

        order_book = state.order_depths[product]
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) == 0 or len(buy_orders) == 0:
            return

        ask, _ = list(sell_orders.items())[-1]  # worst ask
        bid, _ = list(buy_orders.items())[-1]  # worst bid

        fair_price = int(math.ceil((ask + bid) / 2))  # try changing this to floor maybe

        decimal_fair_price = (ask + bid) / 2

        logger.print(f"{product} FAIR PRICE: {decimal_fair_price}")
        self.search_buys(state, product, decimal_fair_price, depth=3)
        self.search_sells(state, product, decimal_fair_price, depth=3)

        # Check if there's another market maker
        best_ask = self.get_ask(state, product, fair_price)
        if best_ask is not None and best_ask - 1 > decimal_fair_price:
            sell_price = best_ask - 1
        else:
            sell_price = math.floor(decimal_fair_price) + 2

        best_bid = self.get_bid(state, product, fair_price)
        if best_bid is not None and best_bid + 1 < decimal_fair_price:
            buy_price = best_bid + 1
        else:
            buy_price = math.floor(decimal_fair_price) - 2

        max_buy = self.limits[product] - self.tomatoes_position - self.tomatoes_buy_orders  # MAXIMUM SIZE OF MARKET ON BUY SIDE
        max_sell = self.tomatoes_position + self.limits[product] - self.tomatoes_sell_orders # MAXIMUM SIZE OF MARKET ON SELL SIDE

        pos = self.tomatoes_position
        # if we are in long, and our best buy price IS the fair price, don't buy more
        if not (pos > 0 and float(buy_price) == decimal_fair_price):
            self.send_buy_order(product, buy_price, max_buy, msg=f"{product}: MARKET MADE Buy {max_buy} @ {buy_price}")

        # if we are in short, and our best sell price IS the fair price, don't sell more
        if not (pos < 0 and float(sell_price) == decimal_fair_price):
            self.send_sell_order(product, sell_price, -max_sell, msg=f"{product}: MARKET MADE Sell {max_sell} @ {sell_price}")

    def reset_orders(self, state: TradingState) -> None:
        self.orders: dict[Symbol, list[Order]] = {}
        self.conversions: int = 0

        self.emeralds_buy_orders: int = 0
        self.emeralds_sell_orders: int = 0
        self.emeralds_position: int = self.get_product_pos(state, "EMERALDS")

        self.tomatoes_buy_orders: int = 0
        self.tomatoes_sell_orders: int = 0
        self.tomatoes_position: int = self.get_product_pos(state, "TOMATOES")

        for product in state.order_depths.keys():
            self.orders[product] = []

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        self.reset_orders(state)

        self.trade_emeralds(state)
        self.trade_tomatoes(state)

        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
