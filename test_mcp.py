import asyncio
from fastmcp import Client
import cv2
import numpy as np
import base64


async def main():
    async with Client("http://localhost:8000/mcp") as client:
        tools = await client.list_tools()
        print("Tools:", tools)

        result1 = await client.call_tool("get_name", {})
        print("Name:", result1.data)

        result2 = await client.call_tool(
            "calculate",
            {
                "a": 2,
                "operator": "+",
                "b": 2
            }
        )
        print("2 + 2 =", result2.data)

        tests = [
            {"a": 10, "operator": "-", "b": 3},
            {"a": -5, "operator": "*", "b": 4},
            {"a": 5, "operator": "/", "b": 2},
        ]

        for t in tests:
            result = await client.call_tool("calculate", t)
            print(t, "=>", result.data)

        shape_base64 = """
        iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAB2ElEQVR4nO3c226CQBRG4U0hKHe+/zNioiaK4IFeNGnStE3mNzO4mVnflReCdnU24iFU8zwbwnwE3g/E0mS+sk6nU8S9VRyzil5Z5/M50Z7fsLLmea6qylboDSurWmepPMcwHWIJiJUy1u12M8eSvl5xniUofQz7vg+/MyvL68rqlX+jQ6wsQenHLAmxBMQqKdbz+VzssTjAl7SylkQsAbEExBIQS0AsAbEExBIQS0AsAbEExBIQS9BYYk3Xmj/3YfIYy8zq+8M8eTT1axsyhgJiCYhlpcea7kk+mM8zVtsk+bvyjJUIsQTEEhBLQKyVx+q6brGzgdXHGoZhsbMByfufQWq73S7WrvKPdTgcYu0q/1gREUtALAGxBMQSEEtArLxiTQ7e6KwmVuvgjc4XL89jFXKONcWe35xjtbHnN89YE1+FheOrsMiu16u6SZ5jGGK73Zqo3FgvIJaAWAJiCYglIJaAWHnFmtx8ntV4/in1l7qpnfw0nEsV5DWGfhBLQCwBsRLHGsfRluLqOtmhsY7H4/ftzWazWFZX1xbm1EHAMUtALAGxfrhcLvY/jll/G8fx9+sYsQSMoRhrv98rm5SLMRQwhgJiCYglIJaAWAJiCYglIJaF+wQjHnMtvKco2QAAAABJRU5ErkJggg==
        """

        shape_result = await client.call_tool(
                        "identify_shape",
                        {"image_base64": shape_base64.strip()}
                        )
        print("Shape:", shape_result.data)

        # ----- test triangle -----
        triangle_img = np.ones((200, 200, 3), dtype=np.uint8) * 255

        triangle_points = np.array([
         [100, 30],
         [30, 170],
         [170, 170]
        ])

        cv2.fillPoly(triangle_img, [triangle_points], (0, 0, 0))

        _, triangle_buffer = cv2.imencode(".png", triangle_img)
        triangle_base64 = base64.b64encode(triangle_buffer).decode("utf-8")

        triangle_result = await client.call_tool(
           "identify_shape",
           {"image_base64": triangle_base64}
        )

        print("Triangle test:", triangle_result.data)


        # ----- test circle -----
        circle_img = np.ones((200, 200, 3), dtype=np.uint8) * 255

        cv2.circle(
         circle_img,
         (100, 100),
          60,
         (0, 0, 0),
          -1
        )


        _, circle_buffer = cv2.imencode(".png", circle_img)
        circle_base64 = base64.b64encode(circle_buffer).decode("utf-8")

        circle_result = await client.call_tool(
           "identify_shape",
           {"image_base64": circle_base64}
        )

        print("Circle test:", circle_result.data)


asyncio.run(main())