[EN](https://github.com/madgagarin/holarchy/blob/main/SECURITY.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/SECURITY.md)

# Política de Seguridad

## Reporte de Vulnerabilidades

Si detecta una posible vulnerabilidad de seguridad en este paquete, por favor no abra un issue público. En su lugar, envíe un correo electrónico a [madgagarin@gmail.com].

Nos tomamos la seguridad muy en serio y responderemos a su reporte a la brevedad.

## Modelo de Seguridad

Este paquete se adhiere al modelo de seguridad de **HLN (Holarchical Logic Network)**, basado en principios de Zero Trust:

- **Arquitectura Zero Trust**: verificación de identidad y firma criptográfica en cada mensaje.
- **Mutual TLS (mTLS)** para comunicaciones seguras y autenticadas entre nodos.
- **Tokens de Acceso de Corta Duración (STS)** con rotación dinámica.
- **Sin Puertos de Entrada para Workers (Modelo PULL)**: los workers inician conexiones salientes hacia el orquestador.
- **Cifrado de Sobre (Envelope Encryption)** para tokens de clientes y workers almacenados en Redis.
- **Protección Criptográfica contra Ataques de Replay**: basada en nonces de un solo uso y marcas de tiempo.

Para consultar los principios detallados, revise la [Especificación de Seguridad de HLN](https://github.com/madgagarin/hln/blob/main/SECURITY.md).
