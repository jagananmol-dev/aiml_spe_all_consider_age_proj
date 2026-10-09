import { Kafka, Producer, Consumer, logLevel } from "kafkajs";

/**
 * VEDA AI — Kafka Client
 *
 * Event-driven backbone for the document processing pipeline.
 * All document state transitions flow through Kafka topics.
 */

// ── Topic Definitions ────────────────────────────────
export const KAFKA_TOPICS = {
  // Document lifecycle
  DOCUMENT_UPLOADED: "veda.documents.uploaded",
  DOCUMENT_PARSED: "veda.documents.parsed",
  DOCUMENT_PARSE_FAILED: "veda.documents.parse-failed",

  // Entity extraction
  ENTITIES_EXTRACTED: "veda.entities.extracted",
  ENTITIES_EXTRACTION_FAILED: "veda.entities.extraction-failed",

  // Knowledge graph
  GRAPH_UPDATED: "veda.graph.updated",
  GRAPH_RELATIONSHIP_CREATED: "veda.graph.relationship-created",

  // Embeddings
  EMBEDDINGS_GENERATED: "veda.embeddings.generated",
  EMBEDDINGS_FAILED: "veda.embeddings.failed",

  // Alerts & notifications
  COMPLIANCE_ALERT: "veda.alerts.compliance",
  MAINTENANCE_ALERT: "veda.alerts.maintenance",
  ANOMALY_DETECTED: "veda.alerts.anomaly",

  // Audit trail
  AUDIT_EVENT: "veda.audit.event",
} as const;

// ── Event Types ──────────────────────────────────────
export interface DocumentUploadedEvent {
  tenantId: string;
  documentId: string;
  fileName: string;
  fileType: string;
  storagePath: string;
  storageBucket: string;
  uploadedBy: string;
  timestamp: string;
}

export interface DocumentParsedEvent {
  tenantId: string;
  documentId: string;
  rawText: string;
  pageCount: number;
  wordCount: number;
  parsedContent: Record<string, unknown>;
  timestamp: string;
}

export interface EntitiesExtractedEvent {
  tenantId: string;
  documentId: string;
  entities: Array<{
    type: string;
    value: string;
    normalizedValue: string;
    confidence: number;
    pageNumber?: number;
    startOffset?: number;
    endOffset?: number;
  }>;
  timestamp: string;
}

export interface GraphUpdatedEvent {
  tenantId: string;
  documentId: string;
  nodesCreated: number;
  edgesCreated: number;
  timestamp: string;
}

export interface AuditEvent {
  tenantId: string;
  userId: string;
  action: string;
  resourceType: string;
  resourceId: string;
  details: Record<string, unknown>;
  timestamp: string;
}

// ── Kafka Client Singleton ───────────────────────────
let kafkaInstance: Kafka | null = null;
let producerInstance: Producer | null = null;

function getKafkaClient(): Kafka {
  if (!kafkaInstance) {
    kafkaInstance = new Kafka({
      clientId: process.env.KAFKA_CLIENT_ID || "veda-ai",
      brokers: (process.env.KAFKA_BROKERS || "localhost:9092").split(","),
      logLevel: logLevel.WARN,
      retry: {
        initialRetryTime: 100,
        retries: 8,
      },
    });
  }
  return kafkaInstance;
}

/**
 * Get or create the Kafka producer singleton.
 */
export async function getProducer(): Promise<Producer> {
  if (!producerInstance) {
    const kafka = getKafkaClient();
    producerInstance = kafka.producer({
      allowAutoTopicCreation: true,
      transactionTimeout: 30000,
    });
    await producerInstance.connect();
  }
  return producerInstance;
}

/**
 * Publish an event to a Kafka topic.
 */
export async function publishEvent<T extends Record<string, unknown>>(
  topic: string,
  event: T,
  key?: string
): Promise<void> {
  const producer = await getProducer();
  await producer.send({
    topic,
    messages: [
      {
        key: key || undefined,
        value: JSON.stringify(event),
        timestamp: Date.now().toString(),
      },
    ],
  });
}

/**
 * Create a Kafka consumer for a specific group.
 */
export async function createConsumer(groupId: string): Promise<Consumer> {
  const kafka = getKafkaClient();
  const consumer = kafka.consumer({ groupId });
  await consumer.connect();
  return consumer;
}

/**
 * Graceful shutdown — disconnect producer and consumers.
 */
export async function disconnectKafka(): Promise<void> {
  if (producerInstance) {
    await producerInstance.disconnect();
    producerInstance = null;
  }
}
