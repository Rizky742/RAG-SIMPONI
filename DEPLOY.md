# Deployment Guide - Hugging Face Spaces

## Prerequisites
- Hugging Face Account
- Docker installed (for local testing)
- Git repository synced with GitHub

## Step 1: Prepare Your Repository

Make sure `.env` file is NOT committed:
```bash
# Add to .gitignore if not already there
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Add .env to gitignore"
```

Check that Dockerfile and .dockerignore are in place:
```bash
ls -la Dockerfile .dockerignore .env.example
```

## Step 2: Create Hugging Face Space

1. Go to https://huggingface.co/new-space
2. Fill in:
   - **Space name**: e.g., `simponi-rag-chatbot`
   - **License**: Choose appropriate license
   - **Space SDK**: Select **Docker**
   - **Private/Public**: Choose based on your needs
3. Click "Create Space"

## Step 3: Set Environment Variables

In your Hugging Face Space settings:

1. Go to **Settings** → **Repository secrets**
2. Add these secrets:
   - `DATABASE_URL`: Your PostgreSQL connection string
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `LLM_MODEL`: Model to use (e.g., `gpt-4o-mini`)
   - `MAX_ROWS_RETURNED`: Max rows to fetch (e.g., `500`)
   - `SQL_TIMEOUT_SECONDS`: Query timeout (e.g., `30`)
   - `APP_ENV`: Set to `production`

## Step 4: Deploy via Git

### Option A: Connect GitHub Repository
1. In Space settings, go to "Repository"
2. Link your GitHub repository
3. The space will auto-deploy on each push to main branch

### Option B: Manual Git Push
```bash
# Add Hugging Face as remote
git remote add huggingface https://huggingface.co/spaces/{username}/{space-name}

# Push to deploy
git push huggingface main
```

## Step 5: Configure Secrets as Environment Variables

Hugging Face Spaces will automatically expose secrets as environment variables. Make sure your `Dockerfile` properly reads from environment:

The current Dockerfile uses:
```dockerfile
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Your `app/config.py` should read from environment variables (which it does via Pydantic Settings).

## Step 6: Test Deployment

Once deployed:
1. Wait for build to complete (check logs in Space)
2. Visit the Space URL
3. Test the API at `/docs` (Swagger UI)
4. Check logs if there are issues

## Troubleshooting

### Database Connection Issues
- Ensure `DATABASE_URL` is set correctly
- Check that PostgreSQL is accessible from Hugging Face (might need to allowlist HF IP ranges)
- If using local DB, consider using a cloud DB service (Railway, Supabase, etc.)

### API Key Issues
- Verify `OPENAI_API_KEY` is set in Space secrets
- Don't expose API keys in code or logs

### Build Failures
- Check Space logs for error messages
- Ensure all `requirements.txt` dependencies are compatible
- Try building locally first: `docker build -t simponi-rag .`

### Port Issues
- Hugging Face Spaces usually exposes the app on port 7860
- The Dockerfile supports `PORT` environment variable
- Default port is 8000

## Local Testing with Docker

Before deploying to HF Spaces, test locally:

```bash
# Build image
docker build -t simponi-rag .

# Run with environment variables
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://..." \
  -e OPENAI_API_KEY="sk-..." \
  -e LLM_MODEL="gpt-4o-mini" \
  simponi-rag

# Visit http://localhost:8000/docs
```

## Production Checklist

- [ ] `.env` is in `.gitignore`
- [ ] All secrets are set in HF Space settings
- [ ] Database is accessible (cloud-hosted recommended)
- [ ] OpenAI API key is valid
- [ ] Dockerfile builds without errors
- [ ] Test API endpoints in deployed Space
- [ ] Check logs for errors after deployment
- [ ] Monitor API usage and costs

## Additional Resources

- [Hugging Face Spaces Documentation](https://huggingface.co/docs/hub/spaces)
- [Hugging Face Spaces Docker Guide](https://huggingface.co/docs/hub/spaces-docker)
- [FastAPI Deployment Guide](https://fastapi.tiangolo.com/deployment/)

## Notes

- The current app uses PostgreSQL - ensure it's cloud-hosted for production
- Consider using a database service like Supabase, Railway, or AWS RDS
- Monitor your OpenAI API usage to avoid unexpected costs
- For production, consider adding authentication to your API
