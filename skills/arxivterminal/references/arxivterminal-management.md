# arxiv Database Management

## Delete All Papers

Remove all papers from the database.

```bash
arxiv delete-all
```

**Warning:** This operation cannot be undone. All papers will be permanently removed from the local database.

## Database Location

- **Database**: `~/Library/Application Support/arxivterminal/papers.db`
- **Logs**: `~/Library/Logs/arxivterminal/arxivterminal.log`

## Backup Database

```bash
# Create backup
cp ~/Library/Application\ Support/arxivterminal/papers.db ~/arxiv-backup.db

# Restore from backup
cp ~/arxiv-backup.db ~/Library/Application\ Support/arxivterminal/papers.db
```

## View Logs

```bash
# View recent logs
tail -f ~/Library/Logs/arxivterminal/arxivterminal.log

# View all logs
cat ~/Library/Logs/arxivterminal/arxivterminal.log
```

## Manual Database Inspection

The database is SQLite format and can be inspected directly:

```bash
sqlite3 ~/Library/Application\ Support/arxivterminal/papers.db
```

Common queries:
```sql
-- List all tables
.tables

-- Count papers
SELECT COUNT(*) FROM papers;

-- View recent papers
SELECT * FROM papers ORDER BY published_date DESC LIMIT 10;
```

## Clean Start

If you want to start fresh:

```bash
# Delete all papers
arxiv delete-all

# Fetch fresh data
arxiv fetch --num-days 3 --categories cs.AI,cs.CL
```
