# player.py

import socket
import json
import threading
import sys
import random
import math
import os
import time
import traceback
from common import User, Game  # Ensure 'common.py' defines User and Game classes appropriately

TRACE = False  # Set to True to enable debug tracing

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class Card:
    def __init__(self, value):
        self.value = value  # e.g., 'A♠', '10♥', 'K♦'

    def __repr__(self):
        return self.value

class Deck:
    def __init__(self):
        suits = ['♣', '♦', '♥', '♠']
        values = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        self.cards = [Card(f"{v}{s}") for s in suits for v in values]
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

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
        try:
            self.t_sock.bind(('', self.t_port))
        except OSError as e:
            print(f"Error binding t_port {self.t_port}: {e}")
            sys.exit(1)
        self.p_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.p_sock.bind(('', self.p_port))
        except OSError as e:
            print(f"Error binding p_port {self.p_port}: {e}")
            sys.exit(1)
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
        self.dealer_info = None
        self.scores = {}
        self.hole_scores = {}      # Store scores for the current hole
        self.hole_winner = None    # Store winner of the current hole
        self.running = True
        self.players_done = set()
        self.in_game = False

        # Flags and data for thread communication
        self.is_my_turn = False
        self.turn_data = {}

        # Initialize turn_event for synchronization
        self.turn_event = threading.Event()

        # Variables to track holes
        self.current_hole = 0
        self.hole_over = False

        # Calculate the port range based on the group number
        self.port_min, self.port_max = self.calculate_port_range(group_number)

        if not (self.port_min <= self.t_port <= self.port_max) or not (self.port_min <= self.p_port <= self.port_max):
            print(f"Port numbers must be in the range {self.port_min}-{self.port_max} for group {self.group_number}")
            sys.exit(1)

        # Initialize set to keep track of received scores
        self.scores_received = set()

        # New attribute to store other players' hands
        self.other_players_hands = {}

        # New attribute to indicate if stealing is allowed
        self.allow_steal = False

    def calculate_port_range(self, group_number):
        if group_number % 2 == 0:  # Even group number
            base_port = (group_number // 2) * 1000 + 1000
            port_min = base_port
            port_max = base_port + 499
        else:  # Odd group number
            base_port = math.ceil(group_number / 2) * 1000 + 500
            port_min = base_port
            port_max = base_port + 499

        return port_min, port_max

    def trace(self, message):
        if TRACE:
            print(f"[TRACE] {message}")

    def get_local_ip(self):
        """Retrieve the local IP address of the machine."""
        try:
            # Connect to a public DNS server to get the local IP address
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            print(f"Error obtaining local IP: {e}")
            return "127.0.0.1"  # Fallback to localhost

    def send_message(self, msg, ip, port, expect_response=False, timeout=5):
        self.trace(f"Sending to {ip}:{port}: {msg}")
        try:
            sock = self.t_sock if port == self.tracker_port else self.p_sock
            sock.sendto(json.dumps(msg).encode(), (ip, port))
            if expect_response:
                sock.settimeout(timeout)
                data, _ = sock.recvfrom(65535)
                self.trace(f"Received from {ip}:{port}: {data}")
                return json.loads(data.decode())
        except socket.timeout:
            print("No response from server. Please try again later.")
        except Exception as e:
            print(f"Error communicating with {ip}:{port}: {e}")
        finally:
            sock.settimeout(None)
        return None

    def send_to_tracker(self, msg):
        return self.send_message(msg, self.tracker_ip, self.tracker_port, expect_response=True)

    def register(self):
        if self.name:
            print("You are already registered.")
            return
        self.name = input("Enter your username: ").strip()
        if not self.name:
            print("Username cannot be empty.")
            return
        local_ip = self.get_local_ip()
        msg = {
            'command': 'register',
            'player': self.name,
            'IPv4': local_ip,
            't-port': self.t_port,
            'p-port': self.p_port
        }
        response = self.send_to_tracker(msg)
        if not response:
            self.name = None
            return
        print(response.get('message', ''))
        if response.get('status') != "SUCCESS":
            self.name = None

    def de_register(self):
        if not self.name:
            print("You are not registered.")
            return
        msg = {'command': 'de_register', 'player': self.name}
        response = self.send_to_tracker(msg)
        if response:
            print(response.get('message', ''))
            if response.get('status') == "SUCCESS":
                self.name = None

    def query_players(self):
        msg = {'command': 'query_players'}
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            players = response.get('players', [])
            self.display_players(players)
        else:
            print("Failed to query players.")

    def query_games(self):
        msg = {'command': 'query_games'}
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            games = response.get('games', [])
            self.display_games(games)
        else:
            print("Failed to query games.")

    def display_players(self, players):
        clear_screen()
        print(f"{Colors.BOLD}{Colors.BLUE}=== Player List ({len(players)} players) ==={Colors.RESET}")
        print(f"{'Username':<15}{'IP':<15}{'T-Port':<10}{'P-Port':<10}{'State':<10}")
        print("-" * 60)
        for player in players:
            print(f"{player['username']:<15}{player['ip']:<15}{player['t_port']:<10}{player['p_port']:<10}{player['state']:<10}")
        print("-" * 60)

    def display_games(self, games):
        clear_screen()
        print(f"{Colors.BOLD}{Colors.BLUE}=== Game List ({len(games)} games) ==={Colors.RESET}")
        for game in games:
            players = ', '.join([p['username'] for p in game['players']])
            print(f"Game ID: {game['id']} | Dealer: {game['dealer']['username']} | Players: {players} | Holes: {game['holes']}")
        if not games:
            print("No active games.")
        print("-" * 60)

    def start_game(self):
        if not self.name:
            print("You must register first.")
            return
        n = self.get_numeric_input("Enter number of additional players (1-3): ", 1, 3)
        if n is None:
            return
        holes = self.get_numeric_input("Enter number of holes (1-9): ", 1, 9)
        if holes is None:
            return
        allow_steal_input = input("Do you want to allow stealing in this game? (yes/no): ").strip().lower()
        if allow_steal_input == 'yes':
            allow_steal = True
        elif allow_steal_input == 'no':
            allow_steal = False
        else:
            print("Invalid input. Please enter 'yes' or 'no'.")
            return

        msg = {
            'command': 'start_game',
            'player': self.name,
            'n': n,
            '#holes': holes,
            'allow_steal': allow_steal
        }
        response = self.send_to_tracker(msg)
        if response and response.get('status') == 'SUCCESS':
            print("Game started successfully. Players have been notified.")
        else:
            print(f"Failed to start game: {response.get('message', '') if response else ''}")

    def get_numeric_input(self, prompt, min_value, max_value):
        try:
            value = int(input(prompt))
            if min_value <= value <= max_value:
                return value
            else:
                print(f"Value must be between {min_value} and {max_value}.")
        except ValueError:
            print("Invalid input.")
        return None

    def start_listening(self):
        if not hasattr(self, 'listener_thread') or not self.listener_thread.is_alive():
            self.listener_thread = threading.Thread(target=self.listen_for_player_messages, daemon=True)
            self.listener_thread.start()

    def listen_for_player_messages(self):
        while self.running:
            try:
                data, addr = self.p_sock.recvfrom(65535)
                msg = json.loads(data.decode())
                command = msg.get('command', '')
                print(f"Received message: {command} from {addr}")
                handler = getattr(self, f"handle_{command}", None)
                if handler:
                    handler(msg, addr)
                else:
                    print(f"Unknown command received: {command}")
            except Exception as e:
                self.trace(f"Error in listen_for_player_messages: {e}")
                traceback.print_exc()

    def handle_assigned_game(self, msg, addr):
        game_id = msg.get('game_id')
        dealer_info = msg.get('dealer')
        players = msg.get('players', [])
        holes = msg.get('holes', 0)
        self.allow_steal = msg.get('allow_steal', False)  # Get allow_steal flag

        # Validation
        if game_id is None or dealer_info is None or not players or holes <= 0:
            self.trace("Invalid assigned_game message received.")
            return

        with self.lock:
            self.game_id = game_id
            self.holes = holes

            self.players_info = [User(**player) for player in players]
            self.dealer_info = User(**dealer_info) if dealer_info else None
            self.is_dealer = (self.name == self.dealer_info.username)
            # Initialize cumulative scores
            self.scores = {player.username: 0 for player in self.players_info}
            self.score = 0
            self.players_done = set()
            self.game_over = False
            self.in_game = True  # Important: Set in_game to True

        clear_screen()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Assigned to Game {self.game_id} ==={Colors.RESET}")
        print(f"Dealer: {Colors.CYAN}{self.dealer_info.username}{Colors.RESET}")
        print(f"Players: {[player.username for player in self.players_info]}")
        print(f"Holes: {self.holes}")
        print(f"Stealing Allowed: {'Yes' if self.allow_steal else 'No'}")  # Display if stealing is allowed

        if self.is_dealer:
            # If the player is the dealer, initiate the game setup
            threading.Thread(target=self.play_game, daemon=True).start()
        else:
            # If not the dealer, wait for the dealer to send hands
            print("Waiting for the dealer to distribute hands...")

    def play_game(self):
        if self.is_dealer:
            threading.Thread(target=self.manage_turns, daemon=True).start()
        else:
            pass  # Non-dealer players wait for their turns

    def initialize_hand(self):
        if len(self.hand) != 6:
            print(f"{Colors.RED}Error: Hand does not contain 6 cards. Found {len(self.hand)} cards.{Colors.RESET}")
            return
        self.hand_grid = [self.hand[:3], self.hand[3:]]
        # Initialize other players' hands and card statuses are set in handle_send_all_hands
        self.print_hand()

    def print_hand(self):
        clear_screen()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== All Players' Hands ==={Colors.RESET}")
        self.print_player_hand(self.name, self.hand_grid, self.card_statuses)
        for username, player_hand in self.other_players_hands.items():
            print()
            self.print_player_hand(username, [player_hand['hand'][:3], player_hand['hand'][3:]], player_hand['card_statuses'])
        print(f"\n{Colors.YELLOW}Discard Pile Top Card:{Colors.RESET} {self.format_card(self.discard_pile[-1].value) if self.discard_pile else 'Empty'}")
        # Add Current Player Score display
        current_score = self.scores.get(self.name, 0)
        print(f"{Colors.BOLD}{Colors.YELLOW}Current Player Score: {current_score}{Colors.RESET}")
        print("=" * 30)

    def print_player_hand(self, username, hand_grid, card_statuses):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {username}'s Hand ==={Colors.RESET}")
        for row in range(2):
            row_display = ""
            for col in range(3):
                card = hand_grid[row][col]
                if card_statuses[row][col]:
                    row_display += self.format_card(card.value) + " "
                else:
                    row_display += self.format_card("??") + " "
            print(row_display)

    def format_card(self, card_value):
        suit_symbols = {'S': '♠', 'H': '♥', 'D': '♦', 'C': '♣'}
        if card_value == "??":
            return f"{Colors.BOLD}{Colors.RED}[ ?? ]{Colors.RESET}"
        value = card_value[:-1]
        suit = card_value[-1]
        suit_symbol = suit if suit in '♠♥♦♣' else suit_symbols.get(suit, '?')
        color = Colors.RED if suit_symbol in ['♥', '♦'] else Colors.BLUE
        return f"{color}[{value}{suit_symbol}]{Colors.RESET}"

    def print_full_hand(self):
        """Print all players' hands with all cards revealed."""
        clear_screen()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== All Players' Full Hands ==={Colors.RESET}")
        # Reveal own hand
        self.print_full_player_hand(self.name, self.hand_grid)
        # Reveal other players' hands
        for username, player_hand in self.other_players_hands.items():
            print()
            hand_grid = [player_hand['hand'][:3], player_hand['hand'][3:]]
            self.print_full_player_hand(username, hand_grid)
        # Display cumulative scores
        if self.scores:
            print(f"\n{Colors.BOLD}{Colors.YELLOW}Final Cumulative Scores:{Colors.RESET}")
            for player, score in self.scores.items():
                print(f"{player}: {score}")
        print("=" * 30)

    def print_full_player_hand(self, username, hand_grid):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {username}'s Full Hand ==={Colors.RESET}")
        for row in range(2):
            row_display = ""
            for col in range(3):
                card = hand_grid[row][col]
                row_display += self.format_card(card.value) + " "
            print(row_display)

    def handle_send_all_hands(self, msg, addr):
        received_hands = msg.get('hands', {})
        received_statuses = msg.get('card_statuses', {})
        dealer_info = msg.get('dealer_info')
        if isinstance(received_hands, dict) and len(received_hands) == len(self.players_info):
            # Initialize hands and card statuses for all players
            self.hand = [Card(val) for val in received_hands[self.name]]
            self.card_statuses = received_statuses[self.name]
            self.hand_grid = [self.hand[:3], self.hand[3:]]
            # Store other players' hands and card statuses
            for username, hand_values in received_hands.items():
                if username != self.name:
                    self.other_players_hands[username] = {
                        'hand': [Card(val) for val in hand_values],
                        'card_statuses': received_statuses[username]
                    }
            self.print_hand()
            self.trace(f"Hand initialized: {self.hand_grid}")
            # Send acknowledgment
            ack_msg = {"status": "SUCCESS", "message": "Hands received and initialized"}
            self.send_message(ack_msg, addr[0], addr[1])
        else:
            self.trace("Invalid hands data received.")
            print(f"{Colors.RED}Error: Received invalid hands data.{Colors.RESET}")
            # Send failure acknowledgment
            ack_msg = {"status": "FAILURE", "message": "Invalid hands data"}
            self.send_message(ack_msg, addr[0], addr[1])
        if dealer_info:
            self.dealer_info = User(**dealer_info)
            print(f"Dealer is {self.dealer_info.username}")
        else:
            print("Failed to receive dealer information.")

    def handle_your_turn(self, msg, addr):
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
            self.current_player_index = msg.get('current_player_index', 0)
            self.is_my_turn = True
            self.turn_data = msg  # Store any additional data if needed
        self.trace(f"Updated stock_pile and discard_pile for turn.")

    def handle_update_piles(self, msg, addr):
        with self.lock:
            self.stock_pile = [Card(val) for val in msg.get('stock_pile', [])]
            self.discard_pile = [Card(val) for val in msg.get('discard_pile', [])]
        self.print_hand()

    def handle_update_hand(self, msg, addr):
        player = msg.get('player')
        hand_values = msg.get('hand')
        card_statuses = msg.get('card_statuses')
        if player and hand_values and card_statuses:
            hand = [Card(val) for val in hand_values]
            hand_grid = [hand[:3], hand[3:]]
            if player != self.name:
                self.other_players_hands[player]['hand'] = hand
                self.other_players_hands[player]['card_statuses'] = card_statuses
            else:
                self.hand_grid = hand_grid
                self.card_statuses = card_statuses
            self.print_hand()

    def handle_end_game(self, msg, addr):
        self.game_over = True
        self.in_game = False
        print("\nGame ended!")

        if self.hand_grid:
            self.print_full_hand()  # Reveal all cards
        else:
            print(f"{Colors.RED}Cannot reveal hand because it is empty.{Colors.RESET}")

        # Receive the final scores
        if 'scores' in msg:
            self.scores = msg['scores']
            winner = msg.get('winner', '')
            self.display_final_scores(winner)
            if self.hand_grid:
                self.print_full_hand()  # Ensure all cards are revealed at game end
        else:
            print("Failed to receive final scores.")

        # Reset game state variables
        self.game_over = True
        self.in_game = False
        self.game_id = None
        self.players_info = []
        self.scores = {}
        self.hole_scores = {}
        self.hole_winner = None
        self.hand = []
        self.hand_grid = []
        self.card_statuses = []
        self.stock_pile = []
        self.discard_pile = []
        self.is_my_turn = False
        self.turn_data = {}
        self.players_done = set()
        self.hole_over = False
        self.current_hole = 0
        self.dealer_info = None
        self.is_dealer = False
        self.score = 0
        print(f"{Colors.GREEN}Game has ended gracefully.{Colors.RESET}")

    def handle_update_player_state(self, msg, addr):
        with self.lock:
            self.current_player_index = msg.get('current_player_index', 0)
            players = msg.get('players', [])
            if players:
                self.players_info = [User(**player) for player in players]
        self.trace(f"Updated current_player_index to {self.current_player_index}")

    def handle_turn_over(self, msg, addr):
        if self.is_dealer:
            self.turn_event.set()
            self.trace("Turn event set by 'turn_over'.")
        else:
            self.trace(f"Received turn_over from {addr}, but not the dealer.")

    def handle_send_score(self, msg, addr):
        self.calculate_score()  # Calculate the current score before sending
        self.send_score(addr)

    def handle_score_response(self, msg, addr):
        player_name = msg.get('player')
        player_score = msg.get('score', 0)
        with self.lock:
            self.hole_scores[player_name] = player_score  # Store hole score
            if self.is_dealer:
                self.scores_received.add(player_name)
                self.trace(f"Received score from {player_name}: {player_score}")
                print(f"{Colors.GREEN}Received score from {player_name}: {player_score}{Colors.RESET}")

    def handle_player_done(self, msg, addr):
        player_name = msg.get('player')
        with self.lock:
            self.players_done.add(player_name)
            if self.is_dealer and self.check_hole_end():
                self.hole_over = True

    def handle_end_hole(self, msg, addr):
        # Handle end of hole message from the dealer
        self.scores = msg.get('scores', self.scores)
        self.hole_scores = msg.get('hole_scores', {})
        self.hole_winner = msg.get('hole_winner', None)
        self.display_current_scores()
        if self.hand_grid:
            self.print_full_hand()  # Reveal all cards
        else:
            print(f"{Colors.RED}Cannot reveal hand because it is empty.{Colors.RESET}")
        self.hole_over = True

    def handle_steal_request(self, msg, addr):
        from_player_name = msg.get('from_player')
        steal_position = msg.get('steal_position')  # (i, j)
        exchange_card_value = msg.get('exchange_card_value')
        exchange_position = msg.get('exchange_position')

        if None in [from_player_name, steal_position, exchange_card_value, exchange_position]:
            print("Invalid steal request.")
            return

        i, j = steal_position
        if not self.card_statuses[i][j]:
            print(f"Cannot steal card at position ({i}, {j}) because it is not face-up.")
            return

        # Swap the cards
        stolen_card = self.hand_grid[i][j]
        self.hand_grid[i][j] = Card(exchange_card_value)
        # The exchanged card is now face-down in the target player's hand
        self.card_statuses[i][j] = False

        # Update own hand
        self.print_hand()

        # Send hand update to other players
        self.send_hand_update()

    def manage_turns(self):
        # Initialize cumulative scores
        with self.lock:
            self.scores = {player.username: 0 for player in self.players_info}
        for hole in range(1, self.holes + 1):
            with self.lock:
                self.current_hole = hole
                self.hole_scores = {}      # Reset hole scores
                self.hole_winner = None    # Reset hole winner
            print(f"\n{Colors.BOLD}{Colors.GREEN}=== Starting Hole {hole}/{self.holes} ==={Colors.RESET}")
            self.setup_hole()
            with self.lock:
                self.players_done = set()
                self.hole_over = False
            while not self.hole_over and self.running:
                with self.lock:
                    current_player = self.players_info[self.current_player_index]
                print(f"\nIt's {Colors.CYAN}{current_player.username}{Colors.RESET}'s turn.")
                if current_player.username == self.name:
                    with self.lock:
                        self.is_my_turn = True
                else:
                    msg = {
                        'command': 'your_turn',
                        'stock_pile': [card.value for card in self.stock_pile],
                        'discard_pile': [card.value for card in self.discard_pile],
                        'current_player_index': self.current_player_index
                    }
                    self.send_message(msg, current_player.ip, current_player.p_port)

                self.turn_event.wait()
                self.turn_event.clear()
                if self.check_hole_end():
                    with self.lock:
                        self.hole_over = True
                    break
                with self.lock:
                    self.current_player_index = (self.current_player_index + 1) % len(self.players_info)
                self.update_player_state()
            # End of hole
            self.end_hole()
            if not self.running:
                break
        # After all holes, declare the winner
        self.declare_winner()

    def setup_hole(self):
        # Dealer sets up the game for the hole
        deck = Deck()
        deck.shuffle()
        self.stock_pile = deck.cards.copy()
        hands = {}
        card_statuses = {}
        for player in self.players_info:
            hand = [self.stock_pile.pop() for _ in range(6)]
            hands[player.username] = hand
            # Generate initial card statuses for this player's hand
            statuses = [[False]*3 for _ in range(2)]
            indices = [(i, j) for i in range(2) for j in range(3)]
            random_indices = random.sample(indices, 2)
            for i, j in random_indices:
                statuses[i][j] = True
            card_statuses[player.username] = statuses
        # Send all hands, card statuses, and dealer info to all players
        for player in self.players_info:
            msg = {
                'command': 'send_all_hands',
                'hands': {username: [card.value for card in hand] for username, hand in hands.items()},
                'card_statuses': card_statuses,
                'dealer_info': self.dealer_info.to_dict()
            }
            self.send_message(msg, player.ip, player.p_port)
        # Initialize dealer's own hand and card statuses
        self.hand = hands[self.name]
        self.card_statuses = card_statuses[self.name]
        self.hand_grid = [self.hand[:3], self.hand[3:]]
        # Initialize other players' hands and card statuses
        for username in hands.keys():
            if username != self.name:
                self.other_players_hands[username] = {
                    'hand': hands[username],
                    'card_statuses': card_statuses[username]
                }
        self.print_hand()
        if not self.stock_pile:
            self.trace("Stock pile is empty after dealing.")
        top_card = self.stock_pile.pop()
        self.discard_pile = [top_card]
        self.current_player_index = 0
        self.update_piles()
        self.update_player_state()

    def check_hole_end(self):
        with self.lock:
            # Hole ends when any player is done (can be modified as per game rules)
            return len(self.players_done) >= 1

    def wait_for_scores(self, timeout=30):
        """Wait for all players to send their scores with a timeout."""
        start_time = time.time()
        while True:
            with self.lock:
                if len(self.scores_received) >= len(self.players_info):
                    return
            if time.time() - start_time > timeout:
                print(f"{Colors.RED}Timeout reached while waiting for scores.{Colors.RESET}")
                return
            time.sleep(0.5)  # Sleep briefly to avoid busy waiting

    def end_hole(self):
        self.calculate_score()
        print(f"\nScore for {self.name} in hole {self.current_hole}: {self.score}")
        if self.is_dealer:
            with self.lock:
                self.hole_scores[self.name] = self.score  # Store dealer's own hole score
                self.scores_received = set([self.name])  # Include dealer's own name
            for player in self.players_info:
                if player.username != self.name:
                    msg = {'command': 'send_score'}
                    self.send_message(msg, player.ip, player.p_port)
            # Wait for all scores to be collected with timeout
            self.wait_for_scores(timeout=30)  # Wait for 30 seconds
            with self.lock:
                # Proceed even if not all scores are received
                missing_players = [p.username for p in self.players_info if p.username not in self.scores_received]
                if missing_players:
                    print(f"{Colors.YELLOW}Did not receive scores from: {', '.join(missing_players)}{Colors.RESET}")
                # Update cumulative scores
                for player_name, hole_score in self.hole_scores.items():
                    self.scores[player_name] += hole_score
                # Determine hole winner
                self.hole_winner = min(self.hole_scores, key=self.hole_scores.get)
            # Send end_hole message with current scores and hole scores
            end_hole_msg = {
                'command': 'end_hole',
                'scores': self.scores,
                'hole_scores': self.hole_scores,
                'hole_winner': self.hole_winner
            }
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(end_hole_msg, player.ip, player.p_port)
            # Display current scores with Current Player Score label
            self.display_current_scores()
            # Reveal all cards for the dealer
            if self.hand_grid:
                self.print_full_hand()  # Dealer reveals their own cards
            # Display results for 10 seconds before proceeding
            print(f"\nNext hole will start in 10 seconds...")
            time.sleep(10)
            with self.lock:
                self.hole_over = True
        else:
            self.send_score((self.dealer_info.ip, self.dealer_info.p_port))
            # Wait for hole_over signal with timeout
            start_time = time.time()
            timeout = 30  # 30 seconds timeout
            while True:
                with self.lock:
                    if self.hole_over:
                        break
                if time.time() - start_time > timeout:
                    print(f"{Colors.RED}Timeout reached while waiting for end of hole.{Colors.RESET}")
                    break
                time.sleep(0.5)
            # Display results for 10 seconds before proceeding
            print(f"\nNext hole will start in 10 seconds...")
            if self.hand_grid:
                self.print_full_hand()  # Non-dealer players reveal their own cards
            else:
                print(f"{Colors.RED}Cannot reveal hand because it is empty.{Colors.RESET}")
            time.sleep(10)
        if self.running:
            self.reset_for_next_hole()

    def reset_for_next_hole(self):
        # Reset game state for the next hole
        self.hand = []
        self.hand_grid = []
        self.card_statuses = []
        self.stock_pile = []
        self.discard_pile = []
        self.is_my_turn = False
        self.turn_data = {}
        self.players_done = set()
        self.game_over = False
        self.hole_over = False
        self.other_players_hands = {}
        self.hole_scores = {}
        self.hole_winner = None
        if self.current_hole < self.holes:
            if self.is_dealer:
                self.setup_hole()
            else:
                print(f"Waiting for dealer {self.dealer_info.username} to start next hole...")
        else:
            self.game_over = True

    def send_score(self, addr):
        msg = {'command': 'score_response', 'player': self.name, 'score': self.score}
        self.send_message(msg, addr[0], addr[1])

    def declare_winner(self):
        winner = min(self.scores, key=self.scores.get)
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Final Scores ==={Colors.RESET}")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        print(f"{Colors.BOLD}{Colors.YELLOW}\nThe winner is {winner}!{Colors.RESET}")
        end_game_msg = {
            'command': 'end_game',
            'scores': self.scores,
            'winner': winner
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(end_game_msg, player.ip, player.p_port)
        # Send end to tracker
        msg = {'command': 'end', 'game-identifier': self.game_id, 'player': self.name}
        response = self.send_to_tracker(msg)
        if response:
            print(response.get('message', ''))
        if self.hand_grid:
            self.print_full_hand()  # Reveal all cards at game end
        else:
            print(f"{Colors.RED}Cannot reveal hand because it is empty.{Colors.RESET}")
        # Reset game state variables
        self.game_over = True
        self.in_game = False
        self.game_id = None
        self.players_info = []
        self.scores = {}
        self.hole_scores = {}
        self.hole_winner = None
        self.hand = []
        self.hand_grid = []
        self.card_statuses = []
        self.stock_pile = []
        self.discard_pile = []
        self.is_my_turn = False
        self.turn_data = {}
        self.players_done = set()
        self.hole_over = False
        self.current_hole = 0
        self.dealer_info = None
        self.is_dealer = False
        self.score = 0
        print(f"{Colors.GREEN}Game has ended gracefully.{Colors.RESET}")

    def calculate_score(self):
        total = 0
        for col in range(3):
            column_cards = [self.hand_grid[row][col] for row in range(2)]
            # Check for pairs in the same column
            if column_cards[0].value[:-1] == column_cards[1].value[:-1]:
                continue  # Score for this column is zero
            for row in range(2):
                card_value = self.card_value(self.hand_grid[row][col].value)
                total += card_value
        self.score = total
        self.trace(f"Calculated score: {self.score}")  # Debug statement

    def card_value(self, card_str):
        value_str = card_str[:-1]
        if value_str == 'A':
            return 1
        elif value_str == '2':
            return -2
        elif value_str in ['J', 'Q']:
            return 10
        elif value_str == 'K':
            return 0
        elif value_str.isdigit():
            return int(value_str)
        else:
            return 0

    def display_current_scores(self):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Current Cumulative Scores After Hole {self.current_hole} ==={Colors.RESET}")
        for player, score in self.scores.items():
            if player == self.name:
                # Highlight the current player's score
                print(f"{Colors.BOLD}{Colors.YELLOW}{player}: {score}{Colors.RESET}")
            else:
                print(f"{player}: {score}")
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Scores for Hole {self.current_hole} ==={Colors.RESET}")
        for player, score in self.hole_scores.items():
            if player == self.name:
                # Highlight the current player's hole score
                print(f"{Colors.BOLD}{Colors.YELLOW}{player}: {score}{Colors.RESET}")
            else:
                print(f"{player}: {score}")
        if self.hole_winner:
            print(f"{Colors.BOLD}{Colors.YELLOW}\nWinner of Hole {self.current_hole}: {self.hole_winner}{Colors.RESET}")
        if self.name in self.scores:
            print(f"{Colors.BOLD}{Colors.YELLOW}\nYour Current Player Score: {self.scores[self.name]}{Colors.RESET}")
        print("=" * 30)

    def display_final_scores(self, winner=None):
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== Final Scores ==={Colors.RESET}")
        for player, score in self.scores.items():
            print(f"{player}: {score}")
        if self.name in self.scores:
            print(f"{Colors.BOLD}{Colors.YELLOW}\nYour final score: {self.scores[self.name]}{Colors.RESET}")
        if winner:
            print(f"{Colors.BOLD}{Colors.YELLOW}\nThe winner is {winner}!{Colors.RESET}")
        print("=" * 30)

    def play_turn(self):
        self.print_hand()
        print(f"{Colors.BOLD}{Colors.GREEN}\n=== {self.name}'s Turn ==={Colors.RESET}")
        if self.discard_pile:
            print(f"{Colors.YELLOW}Discard Pile Top Card:{Colors.RESET} {self.format_card(self.discard_pile[-1].value)}")
        else:
            print("Discard Pile is empty.")
        # Display Current Player Score
        current_score = self.scores.get(self.name, 0)
        print(f"{Colors.BOLD}{Colors.YELLOW}Current Player Score: {current_score}{Colors.RESET}")
        print("\nChoose an action:")
        print(f"{Colors.CYAN}1{Colors.RESET}. Draw from Stock")
        print(f"{Colors.CYAN}2{Colors.RESET}. Draw from Discard")
        if self.allow_steal:
            print(f"{Colors.CYAN}3{Colors.RESET}. Steal a face-up card from another player")
        choice = input("Enter your choice: ").strip()
        if choice == '1':
            self.draw_from_stock()
        elif choice == '2':
            self.draw_from_discard()
        elif choice == '3' and self.allow_steal:
            self.perform_steal()
        else:
            print("Invalid choice. Turn skipped.")
            self.end_turn()

    def perform_steal(self):
        # Display other players and their face-up cards
        available_cards = []
        for player_name, player_hand_info in self.other_players_hands.items():
            face_up_positions = [(i, j) for i in range(2) for j in range(3) if player_hand_info['card_statuses'][i][j]]
            if face_up_positions:
                print(f"\n{player_name}'s face-up cards:")
                for idx, (i, j) in enumerate(face_up_positions):
                    card = player_hand_info['hand'][i*3 + j]
                    card_idx = len(available_cards)  # Indexing over all available cards
                    print(f"{card_idx + 1}. {self.format_card(card.value)} at position ({i}, {j})")
                    available_cards.append({
                        'player_name': player_name,
                        'position': (i, j),
                        'card': card
                    })
        if not available_cards:
            print("No face-up cards available to steal.")
            self.end_turn()
            return

        # Choose a card to steal
        choice = input("Enter the number of the card you want to steal: ").strip()
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(available_cards):
                target_info = available_cards[choice_idx]
            else:
                print("Invalid selection.")
                self.end_turn()
                return
        except ValueError:
            print("Invalid input.")
            self.end_turn()
            return

        # Now, choose a face-down card from your own hand to give in exchange
        face_down_positions = [(i, j) for i in range(2) for j in range(3) if not self.card_statuses[i][j]]
        if not face_down_positions:
            print("You have no face-down cards to exchange. Cannot perform steal action.")
            self.end_turn()
            return

        print("\nChoose a face-down card from your hand to give in exchange:")
        for idx, (i, j) in enumerate(face_down_positions):
            print(f"{idx + 1}. Row {i}, Column {j}")
        try:
            exchange_idx = int(input("Enter the number of the card to exchange: ")) - 1
            if not (0 <= exchange_idx < len(face_down_positions)):
                print("Invalid position selected. Turn skipped.")
                self.end_turn()
                return
            exchange_position = face_down_positions[exchange_idx]
        except ValueError:
            print("Invalid input. Turn skipped.")
            self.end_turn()
            return

        # Get the exchange card value
        i, j = exchange_position
        exchange_card = self.hand_grid[i][j]

        # Prepare and send steal request
        msg = {
            'command': 'steal_request',
            'from_player': self.name,
            'steal_position': target_info['position'],
            'exchange_card_value': exchange_card.value,
            'exchange_position': exchange_position
        }
        target_player = next((p for p in self.players_info if p.username == target_info['player_name']), None)
        if target_player:
            # Send the steal request to the target player
            self.send_message(msg, target_player.ip, target_player.p_port)
            # Update our own hand
            # Swap our face-down card with the stolen card
            i, j = exchange_position
            self.hand_grid[i][j] = target_info['card']
            self.card_statuses[i][j] = True  # The swapped-in card is now face-up

            # Update other player's hand in our records
            other_player_hand_info = self.other_players_hands[target_info['player_name']]
            other_i, other_j = target_info['position']
            other_player_hand_info['hand'][other_i*3 + other_j] = exchange_card
            # The exchanged card is now face-down in the other player's hand
            other_player_hand_info['card_statuses'][other_i][other_j] = False

            # Send hand update to other players
            self.send_hand_update()

            # Print updated hand
            self.print_hand()

            # Check if all our cards are face-up
            if self.is_all_cards_face_up():
                if self.is_dealer:
                    with self.lock:
                        self.players_done.add(self.name)
                    if self.check_hole_end():
                        self.hole_over = True
                else:
                    self.notify_dealer_player_done()

            self.end_turn()
        else:
            print("Target player not found.")
            self.end_turn()

    def is_all_cards_face_up(self):
        return all([status for row in self.card_statuses for status in row])

    def notify_dealer_player_done(self):
        if not self.is_dealer:
            msg = {'command': 'player_done', 'player': self.name}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)

    def draw_from_stock(self):
        with self.lock:
            if not self.stock_pile:
                if len(self.discard_pile) > 1:
                    self.stock_pile = self.discard_pile[:-1]
                    self.discard_pile = [self.discard_pile[-1]]
                    random.shuffle(self.stock_pile)
                    self.trace("Re-shuffled discard pile into stock pile.")
                else:
                    print("No cards left to draw.")
                    self.end_turn()
                    return
            drawn_card = self.stock_pile.pop()
        self.handle_drawn_card(drawn_card)

    def draw_from_discard(self):
        with self.lock:
            if not self.discard_pile:
                print("Discard pile is empty.")
                self.end_turn()
                return
            drawn_card = self.discard_pile.pop()
        self.handle_drawn_card(drawn_card)

    def handle_drawn_card(self, drawn_card):
        print(f"You drew {self.format_card(drawn_card.value)}")
        while True:
            print("\nDo you want to:")
            print(f"{Colors.CYAN}1{Colors.RESET}. Swap a card in your hand")
            print(f"{Colors.CYAN}2{Colors.RESET}. Discard the drawn card")
            action = input("Enter your choice (1 or 2): ").strip()
            if action == '1':
                try:
                    self.print_hand()
                    print("Select the card to swap:")
                    row = int(input("Row (0 or 1): "))
                    col = int(input("Column (0, 1, or 2): "))
                    if not (0 <= row < 2 and 0 <= col < 3):
                        print("Invalid row or column.")
                        continue
                    discarded_card = self.hand_grid[row][col]
                    self.hand_grid[row][col] = drawn_card
                    self.card_statuses[row][col] = True
                    with self.lock:
                        self.discard_pile.append(discarded_card)
                    print(f"Swapped {self.format_card(discarded_card.value)} with {self.format_card(drawn_card.value)}")
                    # Send update to other players
                    self.send_hand_update()
                    break
                except ValueError:
                    print("Invalid input.")
            elif action == '2':
                with self.lock:
                    self.discard_pile.append(drawn_card)
                print(f"Discarded {self.format_card(drawn_card.value)}")
                break
            else:
                print("Invalid action. Please choose again.")
        self.print_hand()
        self.update_piles()
        if self.is_all_cards_face_up():
            if self.is_dealer:
                with self.lock:
                    self.players_done.add(self.name)
                if self.check_hole_end():
                    self.hole_over = True
            else:
                self.notify_dealer_player_done()
        self.end_turn()

    def send_hand_update(self):
        msg = {
            'command': 'update_hand',
            'player': self.name,
            'hand': [card.value for row in self.hand_grid for card in row],
            'card_statuses': self.card_statuses
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(msg, player.ip, player.p_port)

    def end_turn(self):
        if self.is_dealer:
            self.turn_event.set()
        else:
            msg = {'command': 'turn_over'}
            self.send_message(msg, self.dealer_info.ip, self.dealer_info.p_port)

    def update_piles(self):
        msg = {
            'command': 'update_piles',
            'stock_pile': [card.value for card in self.stock_pile],
            'discard_pile': [card.value for card in self.discard_pile]
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(msg, player.ip, player.p_port)

    def update_player_state(self):
        msg = {
            'command': 'update_player_state',
            'current_player_index': self.current_player_index,
            'players': [player.to_dict() for player in self.players_info]
        }
        with self.lock:
            for player in self.players_info:
                if player.username != self.name:
                    self.send_message(msg, player.ip, player.p_port)

    def run(self):
        self.start_listening()
        threading.Thread(target=self.input_thread, daemon=True).start()
        while self.running:
            if self.in_game:
                if self.is_my_turn:
                    self.play_turn()
                    with self.lock:
                        self.is_my_turn = False
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)

    def input_thread(self):
        print(f"{Colors.BOLD}{Colors.GREEN}Welcome to the Card Game!{Colors.RESET}")
        self.show_help()
        while self.running:
            if not self.in_game:
                command = input("\nEnter command (type 'help' for options): ").strip().lower()
                self.handle_command(command)
            else:
                time.sleep(0.1)

    def handle_command(self, command):
        if command == 'register':
            self.register()
        elif command == 'query_players':
            self.query_players()
        elif command == 'query_games':
            self.query_games()
        elif command == 'start_game':
            self.start_game()
        elif command == 'de_register':
            self.de_register()
        elif command == 'help':
            self.show_help()
        elif command == 'exit':
            if self.name:
                self.de_register()
            print("Exiting the game. Goodbye!")
            self.running = False
        else:
            print("Invalid command. Type 'help' to see available commands.")

    def show_help(self):
        help_text = f"""
{Colors.BOLD}{Colors.BLUE}=== Available Commands ==={Colors.RESET}
{Colors.CYAN}register{Colors.RESET}         - Register with the tracker
{Colors.CYAN}query_players{Colors.RESET}    - List all registered players
{Colors.CYAN}query_games{Colors.RESET}      - List all active games
{Colors.CYAN}start_game{Colors.RESET}       - Start a new game
{Colors.CYAN}de_register{Colors.RESET}      - Deregister from the tracker
{Colors.CYAN}help{Colors.RESET}             - Show this help message
{Colors.CYAN}exit{Colors.RESET}             - Exit the application
{Colors.BLUE}========================={Colors.RESET}
"""
        print(help_text)


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
