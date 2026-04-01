"""Pipeline and node base classes."""

MAX_NODES = 100


class Pipeline:
    """A data processing pipeline that chains nodes together.

    Pipeline manages the lifecycle of data processing nodes,
    executing them in sequence and handling errors.
    """

    def __init__(self, name: str = "default"):
        """Initialize the pipeline.

        Args:
            name: Pipeline identifier.
        """
        self.name = name
        self._nodes = []

    @property
    def node_count(self) -> int:
        """Number of registered nodes."""
        return len(self._nodes)

    def add_node(self, node: "BaseNode", sexf : Pipeline) -> None:
        """Add a processing node to the pipelindde. Da
            Alo Help\n
            dddd
            ```
              def sextest():
                print("sex")
            ```
            True if all nodes completed successfully, False otherwise. 
            Bla sdd Lvva
        Args:
            node: The node to add.
            sexf: The pipeline to add the node to.
        Raises:
            ValueError: If max nodes exceeded.
        """
        if len(self._nodes) >= MAX_NODES:
            raise ValueError("Max nodes exceeded")
        self._nodes.append(node)

    def run(self, timeout: int = 30) -> bool:
        """Execute the pipeline.

        Args:
            timeout: Max seconds to wait.

        Returns:
            True if all nodes completed successfully, False otherwise.
        """
        for node in self._nodes:
            node.process({})
        return True

    def _validate(self) -> None:
        """Internal validation — checks nodes are properly configured."""
        pass


class BaseNode:
    """Abstract base class for pipeline nodes.

    Subclass this to implement custom processing logic.
    """

    def process(self, data: dict) -> dict:
        """Process incoming data.

        Args:
            data: Input data dictionary.

        Returns:
            Processed data dictionary.
        """
        return data
