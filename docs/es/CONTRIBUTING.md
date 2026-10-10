[EN](https://github.com/madgagarin/holarchy/blob/main/CONTRIBUTING.md) | **ES** | [RU](https://github.com/madgagarin/holarchy/blob/main/docs/ru/CONTRIBUTING.md)

# Contribución a Holarchy Orchestrator

¡Agradecemos sus contribuciones al proyecto! Por favor, siga estas directrices:

## Configuración del Entorno

1. Clone el repositorio y navegue hasta el directorio raíz del proyecto.
2. Instale el paquete en modo editable con todas las dependencias:
   ```bash
   pip install -e .[all,test]
   ```

## Control de Calidad y Pruebas

Antes de enviar cambios, verifique que todo el código cumpla con los estándares:

```bash
# Linting y formateo
ruff check .
ruff format .

# Verificación de tipos estáticos
mypy src/holarchy

# Ejecución de pruebas del orquestador
pytest tests/
```

## Estándares de Desarrollo

- Todos los cambios deben validarse con **Ruff**.
- Todas las funciones y métodos nuevos deben incluir anotaciones de tipo y pasar las comprobaciones de **Mypy**.
- Mantenga el estilo de diseño existente para máquinas de estados y manejadores de blueprints.
- Conserve los encabezados de licencia MPL-2.0 en todos los archivos de código fuente.
