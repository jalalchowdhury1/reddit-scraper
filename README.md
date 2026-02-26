# Reddit Trending Highlights Scraper

A lightweight Python scraper that fetches the top trending posts from your favorite subreddits and keeps track of what you've already seen. Never miss the top monthly and yearly discussions again!

## 🚀 Features

- **Personalized Subreddit List**: Scrapes a curated list of subreddits (DataIsBeautiful, TIL, Fitness, etc.).
- **Top 5 Highlights**: Specifically fetches the top 5 trending posts for both the **Month** and **Year**.
- **Duplicate Prevention**: Tracks seen posts in a local CSV database (`seen_posts.csv`) so you only see new content.
- **Mirror Support**: Uses various Reddit mirrors to ensure reliability and bypass rate limits.
- **Lightweight & Fast**: Built with `requests` for minimal dependencies and maximum stability.

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/reddit-trending-highlights.git
   cd reddit-trending-highlights
   ```

2. **Install dependencies**:
   ```bash
   pip install requests
   ```

## 📈 Usage

Simply run the script to see your highlights:

```bash
python3 highlights.py
```

To run a test on a single subreddit:

```bash
python3 highlights.py --test
```

## 📂 Project Structure

- `highlights.py`: Main script to manage subreddits and display results.
- `scraper_utils.py`: Core logic for fetching and parsing Reddit data.
- `seen_posts.csv`: (Generated) Local database of seen post IDs.

## 🤝 Contributing

Feel free to fork this project and add your favorite subreddits or improve the formatting!

## 📜 License

MIT License
