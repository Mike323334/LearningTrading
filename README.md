# Trading App - Complete Setup Guide

## Project Overview
A full-stack trading application with automatic buying and selling capabilities.

### Frontend
- **Framework**: HTML5, CSS3, JavaScript (Vanilla)
- **Features**:
  - Trading Dashboard
  - Portfolio Management
  - Watchlist
  - Trade History
  - Strategy Configuration
  - Real-time WebSocket updates
  - P&L Metrics

### Backend
- **Framework**: Python + FastAPI
- **Database**: SQLite (can be changed to PostgreSQL)
- **Real-time**: WebSockets
- **Background Workers**: Automatic trading execution

## Installation & Setup

### Prerequisites
- Python 3.8+
- Node.js 14+ (optional, for development)

### Backend Setup

1. **Navigate to backend directory**:
   ```bash
   cd D:\TradingApp\backend
   ```

2. **Create virtual environment** (optional but recommended):
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the backend server**:
   ```bash
   python app.py
   ```
   
   The server will start on `http://localhost:8000`

### Frontend Setup

1. **Navigate to frontend directory**:
   ```bash
   cd D:\TradingApp\frontend
   ```

2. **Install http-server** (if not already installed):
   ```bash
   npm install -g http-server
   ```

3. **Start the frontend server**:
   ```bash
   http-server -a 0.0.0.0 -p 3000
   ```

4. **Access the application**:
   Open your browser and visit: `http://localhost:3000`

## Usage

### Connecting to the Backend
1. Click the "Connect to Server" button on the dashboard
2. The status indicator should turn green
3. You can now view portfolio, execute trades, and monitor P&L

### Executing Trades
1. Fill in the Strategy Configuration form:
   - Strategy Name
   - Symbol (e.g., AAPL, TSLA)
   - Quantity
   - Trade Side (Buy/Sell)
2. Click "Execute Strategy"
3. The trade will be executed and recorded

### Viewing Trade History
- All executed trades appear in the "Recent Trades" table
- Each trade shows: Symbol, Side, Quantity, Price, and Timestamp

### Monitoring Portfolio
- Portfolio Value: Current total value of your portfolio
- Today's P&L: Profit/Loss for today
- Total P&L: Overall profit/loss since account creation

## API Endpoints

### Backend API
- `GET /` - Health check
- `GET /health` - Detailed health status
- `GET /api/portfolio/{user_id}` - Get user's portfolio
- `POST /api/portfolio/{user_id}/trade` - Execute a trade
- `GET /api/trades/{user_id}` - Get trade history
- `WS /ws/{client_id}` - WebSocket connection

## Configuration

### Changing Database
To use PostgreSQL instead of SQLite:
1. Install PostgreSQL
2. Update `backend/database.py`:
   ```python
   SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost:5432/trading"
   ```

### Adding Redis
To enable Redis caching:
1. Install Redis
2. Update `backend/requirements.txt` to include redis
3. Configure Redis connection in `backend/app.py`

## Troubleshooting

### Connection Issues
- Make sure backend is running on port 8000
- Make sure frontend is running on port 3000
- Check browser console for errors
- Verify CORS settings in `backend/app.py`

### Database Issues
- Delete `trading.db` to reset database
- Check database file permissions

### Port Already in Use
- Find the process using the port: `netstat -ano | findstr :8000`
- Kill the process or use a different port

## Development

### Running in Development Mode
- Backend: `uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000`
- Frontend: `http-server -a 0.0.0.0 -p 3000 --cors`

### API Documentation
FastAPI automatically generates API docs at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Features

### Automatic Trading
The background worker (`auto_trading_worker`) can be configured to:
- Monitor market conditions
- Execute trades based on predefined strategies
- Manage portfolio risk
- Send real-time alerts

### Real-time Updates
WebSocket connections enable:
- Live portfolio updates
- Trade execution confirmations
- Price alerts
- Strategy performance monitoring

### Portfolio Management
- Track multiple assets
- Monitor cash balance
- Calculate P&L in real-time
- View complete trade history

## License
MIT License

## Support
For issues and questions, please refer to the project documentation or contact the development team.# LearningTrading
# LearningTrading
# LearningTrading
