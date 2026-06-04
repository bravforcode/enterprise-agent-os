"""English locale data — first-class data, no faker-js source copied."""
from __future__ import annotations

EN: dict = {
    "person": {
        "first_name_male": [
            "James", "John", "Robert", "Michael", "William", "David", "Richard",
            "Joseph", "Thomas", "Charles", "Christopher", "Daniel", "Matthew",
            "Anthony", "Donald", "Mark", "Paul", "Steven", "Andrew", "Kenneth",
            "George", "Joshua", "Kevin", "Brian", "Edward", "Ronald", "Timothy",
            "Jason", "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric",
            "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon",
            "Frank", "Benjamin", "Gregory", "Samuel", "Raymond", "Patrick",
            "Alexander", "Jack", "Dennis", "Jerry",
        ],
        "first_name_female": [
            "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara",
            "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
            "Sandra", "Margaret", "Ashley", "Kimberly", "Emily", "Donna",
            "Michelle", "Carol", "Amanda", "Melissa", "Deborah", "Stephanie",
            "Rebecca", "Sharon", "Laura", "Cynthia", "Kathleen", "Amy",
            "Shirley", "Angela", "Helen", "Anna", "Brenda", "Pamela",
            "Nicole", "Samantha", "Katherine", "Christine", "Emma", "Ruth",
            "Janet", "Catherine", "Rachel", "Carolyn", "Janet", "Virginia",
            "Maria", "Heather", "Diane", "Julie", "Olivia", "Joyce",
        ],
        "last_name": [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
            "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
            "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
            "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris",
            "Sanchez", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen",
            "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
            "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
            "Mitchell", "Carter", "Roberts", "Phillips", "Evans", "Turner",
            "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart",
        ],
        "prefix_male": ["Mr.", "Dr.", "Prof."],
        "prefix_female": ["Ms.", "Mrs.", "Dr.", "Prof."],
        "gender": ["Male", "Female", "Non-binary"],
        "job_title": [
            "Software Engineer", "Doctor", "Teacher", "Designer", "Architect",
            "Chef", "Artist", "Writer", "Lawyer", "Accountant",
            "Marketing Manager", "Data Scientist", "Product Manager",
            "DevOps Engineer", "Nurse", "Electrician", "Mechanic", "Pilot",
            "Photographer", "Musician", "Civil Engineer", "Project Manager",
            "Sales Representative", "Business Analyst", "Researcher",
            "Journalist", "Veterinarian", "Pharmacist", "Dentist", "Therapist",
        ],
        "interests": [
            "hiking", "reading", "cooking", "photography", "gaming", "music",
            "travel", "yoga", "running", "cycling", "painting", "writing",
            "gardening", "chess", "swimming", "skiing", "surfing", "dancing",
            "baking", "fishing", "knitting", "astronomy", "birdwatching",
        ],
    },
    "location": {
        "city": [
            "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
            "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
            "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte",
            "Indianapolis", "San Francisco", "Seattle", "Denver", "Washington",
            "Boston", "Nashville", "Detroit", "Portland", "Las Vegas", "Memphis",
            "Louisville", "Milwaukee", "Albuquerque", "Tucson", "Sacramento",
            "Atlanta", "Miami", "Raleigh", "Honolulu", "Toronto", "Vancouver",
            "Montreal", "Calgary", "Ottawa", "London", "Manchester", "Bristol",
            "Edinburgh", "Glasgow", "Dublin", "Sydney", "Melbourne", "Auckland",
        ],
        "country": [
            "United States", "Canada", "United Kingdom", "Australia",
            "New Zealand", "Ireland", "France", "Germany", "Spain", "Italy",
            "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria",
            "Sweden", "Norway", "Denmark", "Finland", "Iceland", "Poland",
            "Czech Republic", "Hungary", "Romania", "Greece", "Turkey", "Japan",
            "China", "South Korea", "India", "Singapore", "Thailand", "Malaysia",
            "Indonesia", "Philippines", "Vietnam", "Brazil", "Argentina", "Chile",
            "Mexico", "South Africa", "Egypt", "Nigeria", "Kenya", "Israel",
            "UAE", "Saudi Arabia", "Russia", "Ukraine",
        ],
        "state": [
            "California", "Texas", "Florida", "New York", "Illinois",
            "Pennsylvania", "Ohio", "Georgia", "North Carolina", "Michigan",
            "New Jersey", "Virginia", "Washington", "Arizona", "Massachusetts",
            "Tennessee", "Indiana", "Missouri", "Maryland", "Wisconsin",
        ],
        "street_suffix": ["St", "Ave", "Blvd", "Rd", "Ln", "Dr", "Way", "Pl"],
        "zip_code_format": "#####",
    },
    "phone": {
        "formats": [
            "###-###-####",
            "(###) ###-####",
            "1-###-###-####",
            "###.###.####",
            "###-###-#### x###",
        ],
    },
    "internet": {
        "email_domain": [
            "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
            "icloud.com", "example.com", "protonmail.com", "aol.com",
        ],
        "tld": ["com", "org", "net", "io", "co", "dev", "app"],
        "user_agents": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        ],
    },
    "finance": {
        "currency_code": ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "SGD"],
        "currency_symbol": ["$", "€", "£", "¥", "₹", "฿"],
        "currency_name": [
            "US Dollar", "Euro", "British Pound", "Japanese Yen",
            "Canadian Dollar", "Australian Dollar", "Swiss Franc",
            "Chinese Yuan", "Indian Rupee", "Singapore Dollar",
        ],
        "iban_country": ["US", "GB", "DE", "FR", "IT", "ES", "NL", "BE", "CH", "AT"],
        "credit_card_type": ["visa", "mastercard", "amex", "discover"],
        "crypto_code": ["BTC", "ETH", "LTC", "XRP", "DOGE", "ADA", "SOL", "DOT", "AVAX", "MATIC"],
        "crypto_name": [
            "Bitcoin", "Ethereum", "Litecoin", "Ripple", "Dogecoin",
            "Cardano", "Solana", "Polkadot", "Avalanche", "Polygon",
        ],
    },
    "commerce": {
        "product_adj": [
            "Ergonomic", "Sleek", "Intelligent", "Rustic", "Modern", "Vintage",
            "Handcrafted", "Premium", "Eco-friendly", "Compact", "Portable",
            "Wireless", "Smart", "Durable", "Lightweight", "Heavy-duty",
        ],
        "product_noun": [
            "Chair", "Table", "Lamp", "Keyboard", "Mouse", "Monitor", "Camera",
            "Headphones", "Speaker", "Bag", "Wallet", "Watch", "Bottle", "Mug",
            "Notebook", "Pen", "Backpack", "Shoes", "Jacket", "Hat", "Scarf",
        ],
        "product_material": [
            "Steel", "Wooden", "Plastic", "Leather", "Aluminum", "Glass",
            "Cotton", "Ceramic", "Rubber", "Bamboo", "Marble", "Bronze",
        ],
        "department": [
            "Electronics", "Clothing", "Home & Garden", "Sports", "Books",
            "Toys", "Beauty", "Health", "Automotive", "Grocery", "Office",
            "Pet Supplies", "Tools", "Music", "Movies", "Outdoors",
        ],
    },
    "lorem": {
        "words": (
            "lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
            "eiusmod tempor incididunt ut labore et dolore magna aliqua ut enim "
            "ad minim veniam quis nostrud exercitation ullamco laboris nisi ut "
            "aliquip ex ea commodo consequat duis aute irure dolor in "
            "reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla "
            "pariatur excepteur sint occaecat cupidatat non proident sunt in "
            "culpa qui officia deserunt mollit anim id est laborum sed ut "
            "perspiciatis unde omnis iste natus error sit voluptatem accusantium "
            "doloremque laudantium totam rem aperiam eaque ipsa quae ab illo "
            "inventore veritatis et quasi architecto beatae vitae dicta sunt "
            "explicabo nemo enim ipsam voluptatem quia voluptas sit aspernatur "
            "aut odit aut fugit sed quia consequuntur magni dolores eos qui "
            "ratione voluptatem sequi nesciunt"
        ).split(),
    },
    "date": {
        "month": [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
    },
}
