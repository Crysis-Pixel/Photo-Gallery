# Photo Gallery Application

A full-stack photo gallery application with AI-powered image tagging using CLIP and face detection.

## Features

- 🖼️ Beautiful photo gallery grid layout
- 🏷️ Automatic image tagging using CLIP AI
- 👤 Face detection and person identification
- 🔍 Filter photos by category and scenario
- 📱 Responsive design for all screen sizes
- 🎨 Modern UI with smooth animations
- 📸 Detailed image information and modal viewer

## Project Structure

```
Photo Gallery/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── main.py         # FastAPI app setup
│   │   ├── models.py       # Database models
│   │   ├── schemas.py      # Pydantic schemas
│   │   ├── crud.py         # Database operations and AI tagging
│   │   ├── database.py     # Database configuration
│   │   └── routers/
│   │       └── files.py    # API routes
│   ├── photos/             # Folder for storing photos
│   └── requirements.txt    # Python dependencies
│
└── frontend/               # React + Vite frontend
    ├── src/
    │   ├── App.jsx         # Main app component
    │   ├── App.css         # App styles
    │   ├── index.css       # Global styles
    │   ├── main.jsx        # Entry point
    │   ├── components/
    │   │   ├── PhotoGallery.jsx   # Gallery component
    │   │   └── PhotoCard.jsx      # Photo card component
    │   └── styles/
    │       ├── PhotoGallery.css
    │       └── PhotoCard.css
    ├── package.json
    ├── vite.config.js
    └── index.html
```

## Installation

### Backend Setup

1. Install Python dependencies:
```bash
cd backend
pip install fastapi uvicorn sqlalchemy torch pillow face-recognition python-multipart clip apscheduler
```

2. Create a `.env` file in the backend directory (optional):
```
SCAN_FOLDER=./photos
```

### Frontend Setup

1. Install Node dependencies:
```bash
cd frontend
npm install
```

## Running the Application

### 1. Start the Backend

```bash
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at: `http://localhost:8000`

### 2. Start the Frontend

In a new terminal:

```bash
cd frontend
npm run dev
```

The frontend will be available at: `http://localhost:5173`

## Usage

### Adding Photos

Place image files in the `backend/photos/` directory. The backend will automatically:
- Scan the folder every 5 minutes
- Detect and tag images with categories (work, personal, anime, nature, portrait, food)
- Identify scenarios (meeting, vacation, party, indoor, outdoor, sports)
- Detect faces in images

### Gallery Features

- **Browse**: View all photos in a responsive grid
- **Filter**: Use dropdown menus to filter by category and scenario
- **Details**: Click on any photo to see detailed information including:
  - Full image preview
  - File path
  - Category
  - Scenario
  - Face detection results
  - Upload date and time

## API Endpoints

### Files

- `GET /files/` - Get all photos
- `GET /files/{file_id}/content` - Download photo
- `POST /files/` - Add a new photo
- `PATCH /files/{file_id}` - Update photo metadata
- `POST /files/rescan` - Rescan folder for new photos

Example: Create a new file entry
```bash
curl -X POST "http://localhost:8000/files/" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/path/to/photo.jpg",
    "file_type": "photo",
    "auto_tag": true
  }'
```

## Technologies Used

### Backend
- **FastAPI** - Modern web framework
- **SQLAlchemy** - ORM for database operations
- **CLIP** - OpenAI's vision-language model for image tagging
- **face_recognition** - Face detection library
- **APScheduler** - Background task scheduling

### Frontend
- **React 19** - UI library
- **Vite** - Fast build tool and dev server
- **CSS3** - Styling with modern features

## Configuration

### CLIP Model
The application uses OpenAI's ViT-B/32 CLIP model. The model is automatically downloaded on first run.

### Face Detection
Uses dlib-based face detection. If CUDA is unavailable, processing falls back to CPU.

### Database
SQLite database is created automatically at `backend/app.db`

## Troubleshooting

### Backend won't start
- Ensure Python 3.8+ is installed
- Check that all dependencies are installed
- If CLIP model fails to load, it will automatically fall back to CPU mode

### Frontend won't connect to backend
- Verify backend is running on `http://localhost:8000`
- Check browser console for CORS errors
- Ensure both services are on the same network

### Photos not appearing
- Check that image files are in `backend/photos/` directory
- Ensure supported image formats: JPG, PNG, GIF, BMP, WebP
- Check backend logs for tagging errors

## Future Enhancements

- [ ] Advanced search and full-text search
- [ ] Photo editing tools
- [ ] Album creation and organization
- [ ] User accounts and sharing
- [ ] Bulk operations
- [ ] Photo analytics and statistics
- [ ] Custom AI model training
