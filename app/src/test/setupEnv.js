// Set environment variables for all test environments (client and server)

// Set a default GCS_BUCKET for server-side tests that proxy to GCS.
process.env.GCS_BUCKET = process.env.GCS_BUCKET || 'test-bucket';