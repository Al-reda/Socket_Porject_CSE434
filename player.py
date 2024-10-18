# player.py

import socket
import pickle
import threading
import sys
import random
import math
import os
from common import User, Game  # Ensure common.py defines User and Game appropriately

# Constants for message tracing
TRACE = True  # Set to True to enable message tracing

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

class Card:
    def __init__(self, value):
        self.value = value  # e.g., 'AS', '10D', 'KC'
        self.revealed = False

    def __repr__(self):
        return self.value

class Deck:
    def __init__(self):
        suits = ['C', 'D', 'H', 'S']
        values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        self.cards = [Card(f"{v}{s}") for s in suits for v in values]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def deal(self):
        return self.cards.pop() if self.cards else None

class Player:
    def __init__(self, tracker_ip, tracker_port, t_port, p_port, group_number):
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port
        self.t_port = t_port
        self.p_port = p_port
        self.group_number = group_number
        self.name = None
        self.hand = []
        self.score = 0
        self.t_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.t_sock.bind(('', self.t_port))
        self.p_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.p_sock.bind(('', self.p_port))
        self.players_info = []
        self.game_id = None
        self.holes = 0
        self.is_dealer = False
        self.stock_pile = []
        self.discard_pile = []
        self.hand_grid = []
        self.card_statuses = []
        self.current_player_index = 0
        self.game_over = False
        self.lock = threading.Lock()
        self.turn_event = threading.Event()
        self.turn_event.clear()
        self.dealer_info = None
        self.scores = {}
        self.running = True

        # Calculate the port range based on the group number
        if self.group_number % 2 == 0:  # Even group number
            base_port = (self.group_number // 2) * 1000 + 1000
            self.port_min = base_port
            self.port_max = base_port + 499
        else:  # Odd group number
            base_port = math.ceil(self.group_number / 2) * 1000 + 500
            self.port_min = base_port
            self.port_max = base_port + 499

        if not (self.port_min <= self.t_port <= self.port_max) or not (self.port_min <= self.p_port <= self.port_max):
            print(f"Port numbers must be in the range {self.port_min}-{self.port_max} for group {self.group_number}")
            sys.exit(1)

    def trace(self, message):
        if TRACE:
            print(f"[TRACE] {message}")

    def get_local_ip(self):
        """Retrieve the local IP address of the machine."""
        try:
            # Connect to a public DNS server to get the local IP address
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # This doesn't need to be reachable
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            print(f"Error obtaining local IP: {e}")
            return "127.0.0.1"  # Fallback to localhost

    def send_to_tracker(self, msg):
        self.trace(f"Sending to tracker: {msg}")
        self.t_sock.sendto(pickle.dumps(msg), (self.tracker_ip, self.tracker_port))
        try:
            self.t_sock.settimeout(5)  # Timeout after 5 seconds
            data, _ = self.t_sock.recvfrom(65535)
            self.trace(f"Received from tracker: {data}")
            return data
        except socket.timeout:
            print("No response from tracker. Please try again later.")
            return None
        finally:
            self.t_sock.settimeout(None)  # Reset timeout

    def register(self):
        if self.name:
            print("You are already registered.")
            return
        self.name = input("Enter your username: ").strip()
        if not self.name:
            print("Username cannot be empty.")
            return
        local_ip = self.get_local_ip()  # Get the actual IP address
        msg = {
            'command': 'register',
            'player': self.name,
            'IPv4': local_ip,  # Use the actual IP instead of '127.0.0.1'
            't-port': self.t_port,
            'p-port': self.p_port
        }
        response_data = self.send_to_tracker(msg)
        if not response_data:
            return
        response = response_data.decode()
        print(response)
        if response.startswith("SUCCESS"):
            print(f"Registered successfully as {self.name}")
        else:
            print(f"Registration failed: {response}")
            self.name = None

    def query_players(self):
        msg = {'command': 'query_players'}
        data = self.send_to_tracker(msg)
        if not data:
            return
        response = pickle.loads(data)
        count = response['count']
        players = response['players']
        clear_screen()
        print(f"=== Player List ({count} players) ===")
        print(f"{'Username':<15}{'IP':<15}{'T-Port':<10}{'P-Port':<10}{'State':<10}")
        print("-" * 60)
        for player in players:
            print(f"{player.username:<15}{player.ip:<15}{player.t_port:<10}{player.p_port:<10}{player.state:<10}")
        print("-" * 60)

    def query_games(self):
        msg = {'command': 'query_games'}
        data = self.send_to_tracker(msg)
        if not data:
            return
        response = pickle.loads(data)
        count = response['count']
        games = response['games']
        clear_screen()
        print(f"=== Game List ({count} games) ===")
        for game in games:
            players = ', '.join([p.username for p in game.players])
            print(f"Game ID: {game.id} | Dealer: {game.dealer.username} | Players: {players} | Holes: {game.holes}")
        if count == 0:
            print("No active games.")
        print("-" * 60)

    def start_game(self):
        if not self.name:
            print("You must register first.")
            return
        try:
            n = int(input("Enter number of additional players (1-3): "))
            if not 1 <= n <= 3:
                print("Number of players must be between 1 and 3.")
                return
        except ValueError:
            print("Invalid input for number of players.")
            return

        try:
            holes = int(input("Enter number of holes (1-9): "))
            if not 1 <= holes <= 9:
                print("Number of holes must be between 1 and 9.")
                return
        except ValueError:
            print("Invalid input for number of holes.")
            return

        msg = {
            'command': 'start_game',
            'player': self.name,
            'n': n,
            '#holes': holes
        }
        data = self.send_to_tracker(msg)
        if not data:
            return
        response = pickle.loads(data)
        result = response.get('result')
        if result == "SUCCESS":
            self.game_id = response.get('game_id')
            players = response.get('players', [])
            print(f"\nDEBUG: Game {self.game_id} started with players: {[p.username for p in players]}")
            self.players_info = players
            self.holes = holes
            self.is_dealer = True
            self.dealer_info = next((p for p in self.players_info if p.username == self.name), None)
            self.score = 0
            self.scores = {player.username: 0 for player in self.players_info}

            # Verify players_info is not empty
            if not self.players_info:
                print("ERROR: players_info is empty after starting the game.")
                return

            self.play_game()
        else:
            print(f"Failed to start game: {result}")

    def join_game(self):
        if not self.name:
            print("You must register first.")
            return
        msg = {'command': 'query_games'}
        data = self.send_to_tracker(msg)
        if not data:
            return
        response = pickle.loads(data)
        games = response.get('games', [])

        my_games = [game for game in games if any(p.username == self.name for p in game.players)]
        if not my_games:
            print("You are not part of any ongoing game.")
            return

        game = my_games[0]
        self.game_id = game.id
        self.players_info = game.players
        self.holes = game.holes
        self.is_dealer = (game.dealer.username == self.name)
        self.dealer_info = game.dealer
        self.scores = {player.username: 0 for player in self.players_info}

        # Debug statement
        print(f"DEBUG: Joined game {self.game_id} with players: {[player.username for player in self.players_info]}")

        # Verify players_info is not empty
        if not self.players_info:
            print("ERROR: players_info is empty after joining the game.")
            return

        # Start listening to player messages
        threading.Thread(target=self.listen_for_player_messages, daemon=True).start()

        # Wait for the game to start
        while not self.game_over and self.running:
            self.turn_event.wait()
            self.turn_event.clear()

    def play_game(self):
        print("\nGame started!")
        deck = Deck()
        self.stock_pile = deck.cards.copy()
        hands = {}
        for player in self.players_info:
            hand = [self.stock_pile.pop() for _ in range(6)]
            hands[player.username] = hand
        for player in self.players_info:
            if player.username != self.name:
                self.send_hand(player, hands[player.username])
            else:
                self.hand = hands[player.username]
                self.initialize_hand()
        top_card = self.stock_pile.pop()
        self.discard_pile.append(top_card)
        print(f"Initial discard pile top card: {top_card}")
        threading.Thread(target=self.listen_for_player_messages, daemon=True).start()
        self.current_player_index = 0
        self.manage_turns()

    def send_hand(self, player, hand):
        msg = {
            'command': 'send_hand',
            'hand': [card.value for card in hand]  # Send card values instead of objects
        }
        self.trace(f"Sending hand to {player.username}: {hand}")
        self.p_sock.sendto(pickle.dumps(msg), (player.ip, player.p_port))

    def initialize_hand(self):
        self.hand_grid = [self.hand[:3], self.hand[3:]]
        self.card_statuses = [[False]*3 for _ in range(2)]
        indices = [(i, j) for i in range(2) for j in range(3)]
        if len(indices) < 2:
            print("Not enough cards to reveal.")
            return
        random_indices = random.sample(indices, 2)
        for i, j in random_indices:
            self.card_statuses[i][j] = True
        self.print_hand()

    def print_hand(self):
        clear_screen()
        print(f"\n=== {self.name}'s Hand ===")
        for row in range(2):
            row_display = ""
            for col in range(3):
                if self.card_statuses[row][col]:
                    card = self.hand_grid[row][col]
                    row_display += f"{card.value:<4} "
                else:
                    row_display += "***  "
            print(row_display)
        print("\nDiscard Pile Top Card:", self.discard_pile[-1] if self.discard_pile else "Empty")
        print("="*30)

    def listen_for_player_messages(self):
        while not self.game_over and self.running:
            try:
                data, addr = self.p_sock.recvfrom(65535)
                msg = pickle.loads(data)
                command = msg.get('command', '')
                self.trace(f"Received message from {addr}: {msg}")

                if command == 'send_hand':
                    received_hand = msg.get('hand', [])
                    if isinstance(received_hand, list) and all(isinstance(card_str, str) for card_str in received_hand):
                        self.hand = [Card(val) for val in received_hand]
                        self.initialize_hand()
                    else:
                        self.trace("Invalid hand data received.")
                elif command == 'your_turn':
                    self.turn_event.set()
                elif command == 'update_piles':
                    stock_pile = msg.get('stock_pile', [])
                    discard_pile = msg.get('discard_pile', [])
                    if isinstance(stock_pile, list) and all(isinstance(card_str, str) for card_str in stock_pile):
                        self.stock_pile = [Card(val) for val in stock_pile]
                    else:
                        self.trace("Invalid stock_pile data received.")
                    if isinstance(discard_pile, list) and all(isinstance(card_str, str) for card_str in discard_pile):
                        self.discard_pile = [Card(val) for val in discard_pile]
                    else:
                        self.trace("Invalid discard_pile data received.")
                    self.print_hand()
                elif command == 'end_game':
                    self.game_over = True
                    print("\nGame ended!")
                    self.display_final_scores()
                elif command == 'update_player_state':
                    self.current_player_index = msg.get('current_player_index', 0)
                    self.trace(f"Updating current_player_index to {self.current_player_index}")
                    self.trace(f"Total players: {len(self.players_info)}")
                    if 0 <= self.current_player_index < len(self.players_info):
                        if self.players_info[self.current_player_index].username == self.name:
                            self.turn_event.set()
                    else:
                        self.trace(f"ERROR: Received invalid current_player_index: {self.current_player_index}")
                elif command == 'turn_over':
                    self.turn_event.set()
                elif command == 'steal_card':
                    self.handle_steal_request(msg, addr)
                elif command == 'send_score':
                    self.send_score(addr)
                elif command == 'score_response':
                    player_name = msg.get('player')
                    player_score = msg.get('score', 0)
                    self.scores[player_name] = player_score
                    if len(self.scores) == len(self.players_info):
                        self.declare_winner()
                else:
                    print(f"Unknown command received: {command}")
            except Exception as e:
                self.trace(f"Error in listen_for_player_messages: {e}")

    def manage_turns(self):
        if not self.players_info:
            self.trace("ERROR: players_info is empty. Exiting manage_turns.")
            print("ERROR: No players available to manage turns.")
            return

        self.scores = {player.username: 0 for player in self.players_info}
        while not self.game_over and self.running:
            if not self.players_info:
                self.trace("ERROR: No players in the game. Exiting manage_turns.")
                break
            current_player = self.players_info[self.current_player_index]
            if current_player.username == self.name:
                self.play_turn()
            else:
                msg = {
                    'command': 'your_turn',
                    'stock_pile': [card.value for card in self.stock_pile],
                    'discard_pile': [card.value for card in self.discard_pile],
                    'current_player_index': self.current_player_index
                }
                self.trace(f"Sending 'your_turn' to {current_player.username}")
                self.p_sock.sendto(pickle.dumps(msg), (current_player.ip, current_player.p_port))
            self.turn_event.wait()
            self.turn_event.clear()
            if self.check_game_end():
                self.game_over = True
                self.end_game(self.game_id)
                break
            self.current_player_index = (self.current_player_index + 1) % len(self.players_info)
            self.update_player_state()

    def play_turn(self):
        clear_screen()
        print(f"\n=== {self.name}'s Turn ===")
        self.print_hand()
        print(f"Discard Pile Top Card: {self.discard_pile[-1]}")
        print("\nChoose an action:")
        print("1. Draw from Stock")
        print("2. Draw from Discard")
        print("3. Steal a Card")
        choice = input("Enter your choice (1-3): ").strip()
        if choice == '1':
            self.draw_from_stock()
        elif choice == '2':
            self.draw_from_discard()
        elif choice == '3':
            self.steal_card()
        else:
            print("Invalid choice. Turn skipped.")
            self.end_turn()

    def draw_from_stock(self):
        if not self.stock_pile:
            print("Stock pile is empty. Reshuffling discard pile into stock pile.")
            self.stock_pile = self.discard_pile[:-1]
            self.discard_pile = [self.discard_pile[-1]] if self.discard_pile else []
            random.shuffle(self.stock_pile)
        if not self.stock_pile:
            print("No cards left to draw.")
            self.end_turn()
            return
        drawn_card = self.stock_pile.pop()
        print(f"You drew {drawn_card}")
        self.handle_drawn_card(drawn_card)

    def draw_from_discard(self):
        if not self.discard_pile:
            print("Discard pile is empty.")
            self.end_turn()
            return
        drawn_card = self.discard_pile.pop()
        print(f"You picked up {drawn_card} from discard pile")
        self.handle_drawn_card(drawn_card)

    def handle_drawn_card(self, drawn_card):
        action = input("Do you want to (1) Swap or (2) Discard? ").strip()
        if action == '1':
            try:
                row = int(input("Select row (0 or 1): "))
                col = int(input("Select column (0, 1, or 2): "))
                if not (0 <= row < 2 and 0 <= col < 3):
                    print("Invalid row or column. Action cancelled.")
                    self.discard_pile.append(drawn_card)
                    self.end_turn()
                    return
                discarded_card = self.hand_grid[row][col]
                self.hand_grid[row][col] = drawn_card
                self.card_statuses[row][col] = True
                self.discard_pile.append(discarded_card)
                print(f"Swapped {discarded_card} with {drawn_card}")
            except ValueError:
                print("Invalid input. Action cancelled.")
                self.discard_pile.append(drawn_card)
        elif action == '2':
            self.discard_pile.append(drawn_card)
            print(f"Discarded {drawn_card}")
        else:
            print("Invalid action. Discarding the drawn card.")
            self.discard_pile.append(drawn_card)
        self.print_hand()
        self.update_piles()
        self.end_turn()

    def steal_card(self):
        print("\nPlayers you can steal from:")
        stealable_players = [p for p in self.players_info if p.username != self.name]
        if not stealable_players:
            print("No players available to steal from.")
            self.end_turn()
            return
        for idx, player in enumerate(stealable_players):
            print(f"{idx + 1}. {player.username}")
        try:
            target_idx = int(input("Enter the number of the player to steal from: ")) - 1
            if not (0 <= target_idx < len(stealable_players)):
                print("Invalid player selected. Turn skipped.")
                self.end_turn()
                return
            target_player = stealable_players[target_idx]
        except ValueError:
            print("Invalid input. Turn skipped.")
            self.end_turn()
            return

        msg = {
            'command': 'steal_card',
            'from_player': self.name
        }
        self.trace(f"Sending steal request to {target_player.username}")
        self.p_sock.sendto(pickle.dumps(msg), (target_player.ip, target_player.p_port))
        # Wait for response
        try:
            self.p_sock.settimeout(5)
            data, _ = self.p_sock.recvfrom(65535)
            response = pickle.loads(data)
            if response.get('command') == 'steal_response':
                stolen_card = response.get('card')
                if stolen_card is None:
                    print(f"{target_player.username} has no face-up cards to steal. Turn skipped.")
                else:
                    print(f"Stole card {stolen_card} from {target_player.username}")
                    stolen_card_obj = Card(stolen_card)
                    action = input("Do you want to (1) Swap or (2) Discard the stolen card? ").strip()
                    if action == '1':
                        try:
                            row = int(input("Select row (0 or 1): "))
                            col = int(input("Select column (0, 1, or 2): "))
                            if not (0 <= row < 2 and 0 <= col < 3):
                                print("Invalid row or column. Action cancelled.")
                                self.discard_pile.append(stolen_card_obj)
                                self.end_turn()
                                return
                            discarded_card = self.hand_grid[row][col]
                            self.hand_grid[row][col] = stolen_card_obj
                            self.card_statuses[row][col] = True
                            self.discard_pile.append(discarded_card)
                            print(f"Swapped {discarded_card} with {stolen_card_obj}")
                        except ValueError:
                            print("Invalid input. Action cancelled.")
                            self.discard_pile.append(stolen_card_obj)
                    elif action == '2':
                        self.discard_pile.append(stolen_card_obj)
                        print(f"Discarded {stolen_card_obj}")
                    else:
                        print("Invalid action. Discarding the stolen card.")
                        self.discard_pile.append(stolen_card_obj)
                    self.print_hand()
                    self.update_piles()
            else:
                print(f"Failed to steal from {target_player.username}. Turn skipped.")
        except socket.timeout:
            print("No response from the target player. Turn skipped.")
        finally:
            self.p_sock.settimeout(None)
            self.end_turn()

    def handle_steal_request(self, msg, addr):
        from_player = msg.get('from_player')
        # Choose a random face-up card to give
        face_up_cards = [(i, j) for i in range(2) for j in range(3) if self.card_statuses[i][j]]
        if not face_up_cards:
            # No face-up cards to steal
            response = {'command': 'steal_response', 'card': None}
            self.p_sock.sendto(pickle.dumps(response), addr)
            return
        i, j = random.choice(face_up_cards)
        stolen_card = self.hand_grid[i][j]
        self.card_statuses[i][j] = False
        # Respond with the card value
        response = {'command': 'steal_response', 'card': stolen_card.value}
        self.p_sock.sendto(pickle.dumps(response), addr)
        print(f"DEBUG: {from_player} stole your {stolen_card}")
        self.print_hand()

    def end_turn(self):
        if self.is_dealer:
            self.turn_event.set()
        else:
            # Notify dealer that turn is over
            msg = {'command': 'turn_over'}
            self.p_sock.sendto(pickle.dumps(msg), (self.dealer_info.ip, self.dealer_info.p_port))

    def update_piles(self):
        msg = {
            'command': 'update_piles',
            'stock_pile': [card.value for card in self.stock_pile],
            'discard_pile': [card.value for card in self.discard_pile]
        }
        self.trace("Updating piles to all players")
        for player in self.players_info:
            if player.username != self.name:
                self.p_sock.sendto(pickle.dumps(msg), (player.ip, player.p_port))

    def update_player_state(self):
        if not self.players_info:
            self.trace("ERROR: players_info is empty. Cannot update player state.")
            return
        msg = {
            'command': 'update_player_state',
            'current_player_index': self.current_player_index
        }
        self.trace("Updating player state to all players")
        for player in self.players_info:
            if player.username != self.name:
                self.p_sock.sendto(pickle.dumps(msg), (player.ip, player.p_port))

    def check_game_end(self):
        # Check if any player's all cards are face-up
        for row in self.card_statuses:
            if all(row):
                return True
        return False

    def end_game(self, game_id):
        self.calculate_score()
        print(f"\nFinal score for {self.name}: {self.score}")
        if self.is_dealer:
            self.scores[self.name] = self.score
            for player in self.players_info:
                if player.username != self.name:
                    msg = {'command': 'send_score'}
                    self.trace(f"Requesting score from {player.username}")
                    self.p_sock.sendto(pickle.dumps(msg), (player.ip, player.p_port))
            # Scores from other players will be collected in 'listen_for_player_messages'
        else:
            # Send score to dealer
            self.send_score((self.dealer_info.ip, self.dealer_info.p_port))

    def send_score(self, addr):
        msg = {
            'command': 'score_response',
            'player': self.name,
            'score': self.score
        }
        self.trace(f"Sending score to {addr}: {self.score}")
        self.p_sock.sendto(pickle.dumps(msg), addr)

    def declare_winner(self):
        # Determine winner based on lowest score
        winner = min(self.scores, key=self.scores.get)
        print("\n=== Final Scores ===")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        print(f"\nThe winner is {winner}!")
        # Notify all players to end the game
        end_game_msg = {'command': 'end_game'}
        for player in self.players_info:
            if player.username != self.name:
                self.p_sock.sendto(pickle.dumps(end_game_msg), (player.ip, player.p_port))
        # Notify tracker
        msg = {
            'command': 'end_game',
            'game-identifier': self.game_id,
            'player': self.name
        }
        response = self.send_to_tracker(msg)
        if response:
            print(response.decode())
        self.game_over = True

    def calculate_score(self):
        total = 0
        for col in range(3):
            column_cards = [self.hand_grid[row][col] for row in range(2)]
            if all(self.card_statuses[row][col] for row in range(2)):
                if column_cards[0].value[:-1] == column_cards[1].value[:-1]:
                    continue  # Score for this column is zero
            for row in range(2):
                if self.card_statuses[row][col]:
                    total += self.card_value(self.hand_grid[row][col].value)
        self.score = total

    def card_value(self, card_str):
        value_str = card_str[:-1]  # Remove suit
        if value_str == 'A':
            return 1
        elif value_str == '2':
            return -2
        elif value_str in ['J', 'Q']:
            return 10
        elif value_str == 'K':
            return 0
        else:
            try:
                return int(value_str)
            except ValueError:
                return 0  # For placeholder cards or invalid values

    def display_final_scores(self):
        print("\n=== Final Scores ===")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        if self.name in self.scores:
            print(f"Your final score: {self.scores[self.name]}")
        print("="*30)

    def de_register(self):
        if not self.name:
            print("You are not registered.")
            return
        msg = {
            'command': 'de_register',
            'player': self.name
        }
        response_data = self.send_to_tracker(msg)
        if not response_data:
            return
        response = response_data.decode()
        print(response)
        if response.startswith("SUCCESS"):
            self.name = None

    def show_help(self):
        help_text = """
=== Available Commands ===
register         - Register with the tracker
query_players    - List all registered players
query_games      - List all active games
start_game       - Start a new game
join_game        - Join an existing game
de_register      - Deregister from the tracker
help             - Show this help message
exit             - Exit the application
=========================
"""
        print(help_text)

    def run(self):
        threading.Thread(target=self.listen_for_player_messages, daemon=True).start()
        print("Welcome to the Card Game!")
        self.show_help()
        while self.running:
            command = input("\nEnter command (type 'help' for options): ").strip().lower()
            if command == 'register':
                self.register()
            elif command == 'query_players':
                self.query_players()
            elif command == 'query_games':
                self.query_games()
            elif command == 'start_game':
                self.start_game()
            elif command == 'join_game':
                self.join_game()
            elif command == 'de_register':
                self.de_register()
            elif command == 'help':
                self.show_help()
            elif command == 'exit':
                if self.name:
                    self.de_register()
                print("Exiting the game. Goodbye!")
                self.running = False
                break
            else:
                print("Invalid command. Type 'help' to see available commands.")

if __name__ == '__main__':
    if len(sys.argv) != 6:
        print("Usage: python player.py <tracker_ip> <tracker_port> <t_port> <p_port> <group_number>")
        sys.exit(1)

    tracker_ip = sys.argv[1]
    tracker_port = int(sys.argv[2])
    t_port = int(sys.argv[3])
    p_port = int(sys.argv[4])
    group_number = int(sys.argv[5])

    player = Player(tracker_ip, tracker_port, t_port, p_port, group_number)
    player.run()