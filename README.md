# Shoes Project

A Python-based cryptocurrency analysis and automation tool that interacts with various APIs including CoinGecko, Claude, and Google Sheets to gather, analyze, and process cryptocurrency data.

## Project Overview

This project uses Selenium for web automation, Anthropic's Claude API for intelligent analysis, and various other libraries to track and analyze cryptocurrency metrics. The bot can handle data collection, market analysis, and integrate with external services.

## Features

- Automated cryptocurrency data collection via CoinGecko API
- Historical data storage in SQLite database
- Market analysis with correlation tracking
- Integration with Claude AI for data interpretation
- Google Sheets integration for data export and visualization
- Configurable behavior via environment variables

## Directory Structure

```
shoes/
│
├── README.md                   # Project overview and setup instructions
├── __init__.py                 # Python package initialization
├── architecture.txt            # Project structure documentation
│
├── data/                       # Data directory
│   └── crypto_history.db       # Database file for crypto history
│
├── logs/                       # Logging directory
│   ├── analysis/               # Analysis logs directory
│   │   └── market_analysis.log # Market-related log file
│   │
│   ├── claude.log              # Claude interaction logs
│   ├── claude_api.log          # Claude API logs
│   ├── coingecko.log           # CoinGecko logs
│   ├── coingecko_api.log       # CoinGecko API logs
│   ├── eth_btc_correlation.log # Ethereum/Bitcoin correlation logs
│   ├── google_sheets_api.log   # Google Sheets API logs
│
├── requirements.txt            # Project dependencies
│
└── src/                        # Source code directory
    ├── __init__.py             # Package initialization
    ├── bot.py                  # Main bot implementation
    ├── coingecko_handler.py    # CoinGecko API handler
    ├── config.py               # Configuration management
    ├── database.py             # Database operations
    ├── meme_phrases.py         # Meme-related phrases
    ├── mood_config.py          # Mood configuration settings
    │
    └── utils/                  # Utility modules
        ├── __init__.py         # Utility package initialization
        ├── browser.py          # Browser-related utilities
        ├── logger.py           # Logging utilities
        └── sheets_handler.py   # Spreadsheet handling utilities
```

## Requirements

- Python 3.11+
- Selenium 4.16.0
- Anthropic API key
- CoinGecko API access
- Google Sheets API credentials (optional)

## Installation

1. Clone the repository
   ```bash
   git clone https://github.com/KingRaver/shoes.git
   cd shoes
   ```

2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables by creating a `.env` file in the project root:
   ```
   ANTHROPIC_API_KEY=your_anthropic_api_key
   COINGECKO_API_KEY=your_coingecko_api_key
   # Add other environment variables as needed
   ```

## Usage

Run the main bot script:
```bash
python src/bot.py
```

## Features

- **Data Collection**: Automatically gathers cryptocurrency data from CoinGecko
- **Market Analysis**: Analyzes trends, correlations, and market movements
- **AI Integration**: Uses Claude AI to provide insights on collected data
- **Data Storage**: Stores historical data in SQLite database
- **Reporting**: Generates logs and reports of analysis results

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b new-feature`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin new-feature`
5. Submit a pull request

## License

[MIT]

## Contact

[https://linktr.ee/vvai]
