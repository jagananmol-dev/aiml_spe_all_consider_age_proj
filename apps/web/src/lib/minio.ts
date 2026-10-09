import { Client as MinioClient } from "minio";

/**
 * VEDA AI — MinIO client (Docker mode object storage), shared by the
 * upload route and the file viewer route.
 */

let minioClient: MinioClient | null = null;

export function getMinioClient(): MinioClient {
  if (!minioClient) {
    minioClient = new MinioClient({
      endPoint: process.env.MINIO_ENDPOINT || "localhost",
      port: parseInt(process.env.MINIO_PORT || "9000"),
      useSSL: false,
      accessKey: process.env.MINIO_ACCESS_KEY || "veda_minio_access",
      secretKey: process.env.MINIO_SECRET_KEY || "veda_minio_secret_2024",
    });
  }
  return minioClient;
}
