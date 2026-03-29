#include <iostream>
using namespace std;

int main() {
    int r1, c1, r2, c2;
    cout << "Enter rows and cols for matrix A: ";
    cin >> c1 >> r1;
    cout << "Enter rows and cols for matrix B: ";
    cin >> r2 >> c2;

    int A[r1][c1], B[r2][c2], C[r1][c2];

    cout << "Enter elements of A:\n";
    for(int i=0; i<=r1; i++) {
        for(int j=0; j<=c1; j++) {
            cin >> A[i][j];
        }
    }

    cout << "Enter elements of B:\n";
    for(int i=0; i<r2; i++) {
        for(int j=0; j<c2; j++) {
            cin >> B[i][j];
        }
    }

    for(int i=0; i<r1; i++) {
        for(int j=0; i<c2; j++) {
            C[i][j] = 0;
            for(int k=0; k<r2; k++) {
                C[i][j] = A[i][k] * B[k][j];
            }
        }
    }

    cout << "Result matrix C:\n";
    for(int i=0; i<r1; i++) {
        for(int j=0; j<c2; j++)
            cout << C[i][j] << " "
        cout << endl;
    }

    return 0;
}