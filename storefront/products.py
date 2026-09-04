"""Product catalog for the demo storefront."""

PRODUCTS = [
    {"id": "p1", "name": "Wireless Earbuds Pro", "price": 2499.0, "emoji": "🎧",
     "category": "Audio", "description": "Active noise cancellation, 30hr battery life.", "rating": 4.5},
    {"id": "p2", "name": "Smart Fitness Watch", "price": 4999.0, "emoji": "⌚",
     "category": "Wearables", "description": "Heart rate, SpO2, 7-day battery.", "rating": 4.3},
    {"id": "p3", "name": "Mechanical Keyboard", "price": 3299.0, "emoji": "⌨️",
     "category": "Computing", "description": "Hot-swappable switches, RGB backlight.", "rating": 4.7},
    {"id": "p4", "name": "Portable Bluetooth Speaker", "price": 1799.0, "emoji": "🔊",
     "category": "Audio", "description": "Waterproof, 12hr playtime.", "rating": 4.2},
    {"id": "p5", "name": "4K Webcam", "price": 5499.0, "emoji": "📷",
     "category": "Computing", "description": "Auto-focus, built-in ring light.", "rating": 4.4},
    {"id": "p6", "name": "Ergonomic Laptop Stand", "price": 1299.0, "emoji": "💻",
     "category": "Accessories", "description": "Adjustable height, aluminum build.", "rating": 4.6},
    {"id": "p7", "name": "Noise-Cancelling Headphones", "price": 6999.0, "emoji": "🎵",
     "category": "Audio", "description": "Studio-grade ANC, 40hr battery.", "rating": 4.8},
    {"id": "p8", "name": "Smart Home Hub", "price": 3999.0, "emoji": "🏠",
     "category": "Smart Home", "description": "Voice control, works with all major brands.", "rating": 4.1},
    {"id": "p9", "name": "Wireless Charging Pad", "price": 899.0, "emoji": "🔌",
     "category": "Accessories", "description": "15W fast charging, sleek design.", "rating": 4.3},
    {"id": "p10", "name": "Gaming Mouse", "price": 1999.0, "emoji": "🖱️",
     "category": "Computing", "description": "16000 DPI, customizable RGB.", "rating": 4.6},
    {"id": "p11", "name": "Portable Power Bank", "price": 1599.0, "emoji": "🔋",
     "category": "Accessories", "description": "20000mAh, dual USB-C ports.", "rating": 4.4},
    {"id": "p12", "name": "Smart LED Desk Lamp", "price": 2199.0, "emoji": "💡",
     "category": "Smart Home", "description": "Adjustable warmth, app-controlled.", "rating": 4.0},
]

PRODUCTS_BY_ID = {p["id"]: p for p in PRODUCTS}
CATEGORIES = sorted({p["category"] for p in PRODUCTS})
